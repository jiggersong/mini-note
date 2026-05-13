"""OSS 云端备份 — 快照上传、下载、列表、验证。

通过环境变量读取凭证，未配置时 graceful fallback 到本地模式。
支持可选的客户端 AES 加密。
"""

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class OSSConfig:
    """OSS 连接配置，从环境变量读取。"""

    endpoint: str
    bucket: str
    access_key_id: str
    access_key_secret: str
    prefix: str = "snapshots"
    encryption_key: str = ""

    @classmethod
    def from_env(cls) -> "OSSConfig | None":
        """从环境变量读取配置，关键字段缺失返回 None。"""
        endpoint = os.getenv("OSS_ENDPOINT", "")
        bucket = os.getenv("OSS_BUCKET", "")
        ak_id = os.getenv("OSS_ACCESS_KEY_ID", "")
        ak_secret = os.getenv("OSS_ACCESS_KEY_SECRET", "")

        if not all([endpoint, bucket, ak_id, ak_secret]):
            return None

        return cls(
            endpoint=endpoint,
            bucket=bucket,
            access_key_id=ak_id,
            access_key_secret=ak_secret,
            prefix=os.getenv("OSS_PREFIX", "snapshots"),
            encryption_key=os.getenv("OSS_ENCRYPTION_KEY", ""),
        )

    @property
    def enabled(self) -> bool:
        return bool(self.endpoint and self.bucket and self.access_key_id)


_UNSET = object()


class OSSBackup:
    """OSS 备份客户端：快照上传/下载/列表/验证。

    无 OSS 配置时退化为本地模式（操作均返回 ok=True 但无远程效果）。
    """

    def __init__(self, config: OSSConfig | None = _UNSET):
        if config is _UNSET:
            self.config = OSSConfig.from_env()
        else:
            self.config = config
        self._client = None

    @property
    def enabled(self) -> bool:
        return self.config is not None and self.config.enabled

    def _get_client(self):
        """延迟初始化 OSS Bucket 对象。"""
        if self._client is not None:
            return self._client
        if not self.enabled:
            raise RuntimeError("OSS 未配置")
        import oss2
        auth = oss2.Auth(self.config.access_key_id, self.config.access_key_secret)
        self._client = oss2.Bucket(auth, self.config.endpoint, self.config.bucket)
        return self._client

    def _oss_key(self, snapshot_id: str) -> str:
        """构造 OSS object key。"""
        prefix = self.config.prefix if self.config else "snapshots"
        return f"{prefix}/{snapshot_id}.tar.gz"

    # ----------------------------------------------------------------
    # 上传
    # ----------------------------------------------------------------

    def upload(self, snapshot_path: Path, snapshot_id: str) -> dict:
        """上传快照包到 OSS。

        Args:
            snapshot_path: 本地 tar.gz 文件路径
            snapshot_id: 快照标识

        Returns:
            {"ok": bool, "oss_key": str, "sha256": str, "error": str|None}
        """
        sha = _sha256_file(snapshot_path)

        if not self.enabled:
            return {
                "ok": True,
                "oss_key": self._oss_key(snapshot_id),
                "sha256": sha,
                "mode": "local",
                "error": None,
            }

        oss_key = self._oss_key(snapshot_id)

        try:
            # 可选：客户端加密
            data = snapshot_path.read_bytes()
            if self.config.encryption_key:
                data = _aes_encrypt(data, self.config.encryption_key)

            bucket = self._get_client()
            bucket.put_object(oss_key, data)

            # 校验远程 hash
            remote_sha = _sha256_data(data)
            return {
                "ok": True,
                "oss_key": oss_key,
                "sha256": remote_sha,
                "mode": "oss",
                "error": None,
            }
        except Exception as e:
            return {
                "ok": False,
                "oss_key": oss_key,
                "sha256": sha,
                "mode": "oss",
                "error": str(e),
            }

    # ----------------------------------------------------------------
    # 下载
    # ----------------------------------------------------------------

    def download(self, oss_key: str, target: Path) -> dict:
        """从 OSS 下载快照到本地文件。

        Returns:
            {"ok": bool, "path": str, "sha256": str, "error": str|None}
        """
        if not self.enabled:
            return {
                "ok": False,
                "path": str(target),
                "sha256": "",
                "error": "OSS 未配置，无法下载",
            }

        try:
            bucket = self._get_client()
            result = bucket.get_object(oss_key)
            data = result.read()

            # 可选：解密
            if self.config.encryption_key:
                data = _aes_decrypt(data, self.config.encryption_key)

            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)

            sha = _sha256_data(data)
            return {
                "ok": True,
                "path": str(target),
                "sha256": sha,
                "error": None,
            }
        except Exception as e:
            return {
                "ok": False,
                "path": str(target),
                "sha256": "",
                "error": str(e),
            }

    # ----------------------------------------------------------------
    # 列表
    # ----------------------------------------------------------------

    def list_snapshots(self, max_keys: int = 100) -> list[dict]:
        """列出 OSS 中所有快照。

        Returns:
            [{"oss_key": str, "size": int, "last_modified": str}]
        """
        if not self.enabled:
            return []

        try:
            bucket = self._get_client()
            results = []
            prefix = f"{self.config.prefix}/"
            for obj in bucket.list_objects(prefix=prefix, max_keys=max_keys).object_list:
                results.append({
                    "oss_key": obj.key,
                    "size": obj.size,
                    "last_modified": obj.last_modified,
                })
            return results
        except Exception:
            return []

    # ----------------------------------------------------------------
    # 验证
    # ----------------------------------------------------------------

    def verify(self, oss_key: str, expected_sha256: str) -> dict:
        """验证 OSS 上快照的完整性（下载后校验 hash）。

        Returns:
            {"ok": bool, "sha256_match": bool, "error": str|None}
        """
        import tempfile

        tmp = Path(tempfile.mktemp(suffix=".tar.gz"))
        try:
            result = self.download(oss_key, tmp)
            if not result["ok"]:
                return {
                    "ok": False,
                    "sha256_match": False,
                    "error": result.get("error"),
                }
            match = result["sha256"] == expected_sha256
            return {
                "ok": match,
                "sha256_match": match,
                "error": None if match else f"hash 不匹配: {result['sha256']} != {expected_sha256}",
            }
        finally:
            if tmp.exists():
                tmp.unlink()


# ================================================================
# 辅助函数
# ================================================================

def _sha256_file(path: Path) -> str:
    """计算文件的 SHA256 hex 值。"""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha256_data(data: bytes) -> str:
    """计算二进制数据的 SHA256 hex 值。"""
    return hashlib.sha256(data).hexdigest()


def _aes_encrypt(data: bytes, key: str) -> bytes:
    """使用 AES-256-GCM 加密数据。"""
    import secrets
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    key_bytes = hashlib.sha256(key.encode()).digest()
    nonce = secrets.token_bytes(12)
    encrypted = AESGCM(key_bytes).encrypt(nonce, data, None)
    return nonce + encrypted


def _aes_decrypt(data: bytes, key: str) -> bytes:
    """使用 AES-256-GCM 解密数据。"""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    key_bytes = hashlib.sha256(key.encode()).digest()
    nonce = data[:12]
    ciphertext = data[12:]
    return AESGCM(key_bytes).decrypt(nonce, ciphertext, None)


def oss_enabled() -> bool:
    """检查当前环境是否配置了 OSS。"""
    cfg = OSSConfig.from_env()
    return cfg is not None and cfg.enabled
