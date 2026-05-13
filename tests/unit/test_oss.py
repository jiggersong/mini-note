"""OSS 备份单元测试 — 配置解析、本地模式、AES 加解密、hash 辅助函数。"""

import hashlib
import tempfile
from pathlib import Path

import pytest


class TestOSSConfig:
    """测试 OSSConfig.from_env() 配置读取。"""

    def test_from_env_all_vars_set(self, monkeypatch):
        """完整环境变量返回配置对象。"""
        monkeypatch.setenv("OSS_ENDPOINT", "https://oss-cn-hangzhou.aliyuncs.com")
        monkeypatch.setenv("OSS_BUCKET", "my-bucket")
        monkeypatch.setenv("OSS_ACCESS_KEY_ID", "ak-test")
        monkeypatch.setenv("OSS_ACCESS_KEY_SECRET", "sk-test")
        monkeypatch.setenv("OSS_PREFIX", "backups")

        from mini_note.backup.oss import OSSConfig

        cfg = OSSConfig.from_env()
        assert cfg is not None
        assert cfg.endpoint == "https://oss-cn-hangzhou.aliyuncs.com"
        assert cfg.bucket == "my-bucket"
        assert cfg.access_key_id == "ak-test"
        assert cfg.prefix == "backups"
        assert cfg.enabled is True

    def test_from_env_all_vars_set_default_prefix(self, monkeypatch):
        """未设置 OSS_PREFIX 时使用默认前缀。"""
        monkeypatch.setenv("OSS_ENDPOINT", "https://oss.example.com")
        monkeypatch.setenv("OSS_BUCKET", "bucket")
        monkeypatch.setenv("OSS_ACCESS_KEY_ID", "ak")
        monkeypatch.setenv("OSS_ACCESS_KEY_SECRET", "sk")

        from mini_note.backup.oss import OSSConfig

        cfg = OSSConfig.from_env()
        assert cfg is not None
        assert cfg.prefix == "snapshots"

    def test_from_env_missing_all(self, monkeypatch):
        """无任何环境变量返回 None。"""
        monkeypatch.delenv("OSS_ENDPOINT", raising=False)
        monkeypatch.delenv("OSS_BUCKET", raising=False)
        monkeypatch.delenv("OSS_ACCESS_KEY_ID", raising=False)
        monkeypatch.delenv("OSS_ACCESS_KEY_SECRET", raising=False)

        from mini_note.backup.oss import OSSConfig

        cfg = OSSConfig.from_env()
        assert cfg is None

    def test_from_env_partial_config(self, monkeypatch):
        """部分环境变量（缺 ACCESS_KEY_SECRET）返回 None。"""
        monkeypatch.setenv("OSS_ENDPOINT", "https://oss.example.com")
        monkeypatch.setenv("OSS_BUCKET", "bucket")
        monkeypatch.setenv("OSS_ACCESS_KEY_ID", "ak")
        monkeypatch.delenv("OSS_ACCESS_KEY_SECRET", raising=False)

        from mini_note.backup.oss import OSSConfig

        cfg = OSSConfig.from_env()
        assert cfg is None

    def test_from_env_missing_endpoint(self, monkeypatch):
        """缺 ENDPOINT 返回 None。"""
        monkeypatch.delenv("OSS_ENDPOINT", raising=False)
        monkeypatch.setenv("OSS_BUCKET", "bucket")
        monkeypatch.setenv("OSS_ACCESS_KEY_ID", "ak")
        monkeypatch.setenv("OSS_ACCESS_KEY_SECRET", "sk")

        from mini_note.backup.oss import OSSConfig

        cfg = OSSConfig.from_env()
        assert cfg is None

    def test_oss_enabled_helper_true(self, monkeypatch):
        """oss_enabled() 配置完整时返回 True。"""
        monkeypatch.setenv("OSS_ENDPOINT", "https://oss.example.com")
        monkeypatch.setenv("OSS_BUCKET", "bucket")
        monkeypatch.setenv("OSS_ACCESS_KEY_ID", "ak")
        monkeypatch.setenv("OSS_ACCESS_KEY_SECRET", "sk")

        from mini_note.backup.oss import oss_enabled

        assert oss_enabled() is True

    def test_oss_enabled_helper_false(self, monkeypatch):
        """oss_enabled() 无配置时返回 False。"""
        monkeypatch.delenv("OSS_ENDPOINT", raising=False)
        monkeypatch.delenv("OSS_BUCKET", raising=False)
        monkeypatch.delenv("OSS_ACCESS_KEY_ID", raising=False)
        monkeypatch.delenv("OSS_ACCESS_KEY_SECRET", raising=False)

        from mini_note.backup.oss import oss_enabled

        assert oss_enabled() is False


class TestOSSBackupLocalMode:
    """OSS 未配置时，操作以本地模式运行、不上传也不报错。"""

    def test_upload_in_local_mode(self, tmp_path):
        """无 OSS 配置时 upload 返回 ok=True + mode=local。"""
        from mini_note.backup.oss import OSSBackup, OSSConfig

        oss = OSSBackup(config=None)  # 明确传 None，不读环境变量
        p = tmp_path / "test.tar.gz"
        p.write_bytes(b"fake snapshot data")

        result = oss.upload(p, "snap-test-001")
        assert result["ok"] is True
        assert result["mode"] == "local"
        assert "oss_key" in result
        assert "sha256" in result
        assert result["error"] is None

    def test_upload_sha256_is_deterministic(self, tmp_path):
        """相同内容两次 upload 产生相同 sha256。"""
        from mini_note.backup.oss import OSSBackup

        oss = OSSBackup(config=None)
        p = tmp_path / "test.tar.gz"
        p.write_bytes(b"deterministic content")

        r1 = oss.upload(p, "snap-1")
        r2 = oss.upload(p, "snap-2")
        assert r1["sha256"] == r2["sha256"]

    def test_download_in_local_mode_returns_error(self, tmp_path):
        """无 OSS 配置时 download 返回 ok=False。"""
        from mini_note.backup.oss import OSSBackup

        oss = OSSBackup(config=None)
        target = tmp_path / "downloaded.tar.gz"
        result = oss.download("snapshots/snap-test.tar.gz", target)
        assert result["ok"] is False
        assert "OSS 未配置" in result.get("error", "")

    def test_list_snapshots_local_mode(self):
        """无 OSS 配置时 list_snapshots 返回空列表。"""
        from mini_note.backup.oss import OSSBackup

        oss = OSSBackup(config=None)
        result = oss.list_snapshots()
        assert result == []

    def test_oss_key_with_config(self):
        """有配置时 _oss_key 使用配置中的 prefix。"""
        from mini_note.backup.oss import OSSBackup, OSSConfig

        cfg = OSSConfig(
            endpoint="https://oss.example.com",
            bucket="bucket",
            access_key_id="ak",
            access_key_secret="sk",
            prefix="my-prefix",
        )
        oss = OSSBackup(config=cfg)
        assert oss._oss_key("snap-001") == "my-prefix/snap-001.tar.gz"

    def test_oss_key_without_config(self):
        """无配置时 _oss_key 使用默认 prefix。"""
        from mini_note.backup.oss import OSSBackup

        oss = OSSBackup(config=None)
        assert oss._oss_key("snap-001") == "snapshots/snap-001.tar.gz"

    def test_verify_local_mode(self, tmp_path):
        """verify 在无配置时尝试下载失败。"""
        from mini_note.backup.oss import OSSBackup

        oss = OSSBackup(config=None)
        result = oss.verify("some-key", "abc123")
        assert result["ok"] is False
        assert result["sha256_match"] is False


class TestSHA256:
    """测试 SHA256 辅助函数。"""

    def test_sha256_file_known_value(self, tmp_path):
        """空文件 SHA256 应与已知值一致。"""
        from mini_note.backup.oss import _sha256_file

        p = tmp_path / "empty.bin"
        p.write_bytes(b"")
        assert _sha256_file(p) == hashlib.sha256(b"").hexdigest()

    def test_sha256_file_with_content(self, tmp_path):
        """有内容文件的 SHA256。"""
        from mini_note.backup.oss import _sha256_file

        p = tmp_path / "data.bin"
        p.write_bytes(b"hello world")
        assert _sha256_file(p) == hashlib.sha256(b"hello world").hexdigest()

    def test_sha256_data_known_value(self):
        """数据 SHA256 与标准库一致。"""
        from mini_note.backup.oss import _sha256_data

        assert _sha256_data(b"test") == hashlib.sha256(b"test").hexdigest()

    def test_sha256_data_different_content(self):
        """不同内容产生不同 hash。"""
        from mini_note.backup.oss import _sha256_data

        h1 = _sha256_data(b"alpha")
        h2 = _sha256_data(b"beta")
        assert h1 != h2

    def test_sha256_file_nonexistent_raises(self, tmp_path):
        """不存在的文件应抛出 FileNotFoundError。"""
        from mini_note.backup.oss import _sha256_file

        with pytest.raises(FileNotFoundError):
            _sha256_file(tmp_path / "does-not-exist.bin")


class TestAES:
    """测试 AES-256-GCM 加解密。"""

    def test_encrypt_decrypt_roundtrip(self):
        """加密后解密恢复原始数据。"""
        from mini_note.backup.oss import _aes_encrypt, _aes_decrypt

        original = "这是一段需要加密的敏感备份数据。".encode("utf-8") * 10
        key = "my-secret-key-2026"

        encrypted = _aes_encrypt(original, key)
        # 加密后输出包含 12 字节 nonce + 密文 + 16 字节 tag
        assert len(encrypted) > len(original)
        assert encrypted != original

        decrypted = _aes_decrypt(encrypted, key)
        assert decrypted == original

    def test_encrypt_empty_data(self):
        """加密空数据不崩溃。"""
        from mini_note.backup.oss import _aes_encrypt, _aes_decrypt

        key = "test-key"
        encrypted = _aes_encrypt(b"", key)
        assert len(encrypted) > 0  # nonce + tag
        assert _aes_decrypt(encrypted, key) == b""

    def test_encrypt_different_keys_produce_different_output(self):
        """不同密钥加密相同数据产生不同密文。"""
        from mini_note.backup.oss import _aes_encrypt

        data = b"sensitive content"
        c1 = _aes_encrypt(data, "key-alpha")
        c2 = _aes_encrypt(data, "key-beta")
        assert c1 != c2

    def test_encrypt_same_key_produce_different_ciphertext(self):
        """相同密钥加密两次产生不同密文（随机 nonce）。"""
        from mini_note.backup.oss import _aes_encrypt

        data = b"repeatable content"
        c1 = _aes_encrypt(data, "key-same")
        c2 = _aes_encrypt(data, "key-same")
        # nonce 随机，密文不同
        assert c1 != c2

    def test_decrypt_wrong_key_raises(self):
        """错误密钥解密应抛出异常。"""
        from mini_note.backup.oss import _aes_encrypt, _aes_decrypt

        encrypted = _aes_encrypt(b"secret", "correct-key")
        with pytest.raises(Exception):
            _aes_decrypt(encrypted, "wrong-key")

    def test_decrypt_corrupted_data_raises(self):
        """篡改过的密文解密失败。"""
        from mini_note.backup.oss import _aes_decrypt

        corrupted = b"\x00" * 100  # 无效密文
        with pytest.raises(Exception):
            _aes_decrypt(corrupted, "any-key")

    def test_encrypt_large_data(self):
        """加密大文件（约 5MB）不崩溃且正确恢复。"""
        from mini_note.backup.oss import _aes_encrypt, _aes_decrypt

        data = b"A" * (5 * 1024 * 1024)
        key = "large-data-key"
        encrypted = _aes_encrypt(data, key)
        decrypted = _aes_decrypt(encrypted, key)
        assert decrypted == data
