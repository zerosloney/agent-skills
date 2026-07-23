"""密钥链密码加密实现 - 跨平台安全方案

跨平台安全方案：
- Windows: keyrings.windows.Windows (Credential Locker)
- macOS: keyrings.macOS.Keyring (Keychain)
- Linux: SecretService (GNOME Keyring/KWallet)

安装依赖：
    pip install keyring
    # 平台特定后端（可选，自动检测）
    pip install keyrings.windows    # Windows
    pip install keyrings.macOS      # macOS
    pip install secretstorage       # Linux (GNOME Keyring)
"""

import warnings
from typing import Optional

# 尝试导入 keyring
try:
    import keyring as keyring_module

    _HAS_KEYRING = True
except ImportError:
    _HAS_KEYRING = False

_SERVICE_NAME = "database-explorer"


def save_password(conn_name: str, password: str, use_keyring: bool = True) -> Optional[str]:
    """保存密码

    Args:
        conn_name: 连接名称
        password: 明文密码
        use_keyring: 是否使用密钥链（默认 True）

    Returns:
        加密后的密码（非密钥链模式），密钥链模式返回 None
    """

    if not password:
        return None

    # 优先使用密钥链
    if use_keyring and _HAS_KEYRING:
        try:
            keyring_module.set_password(_SERVICE_NAME, conn_name, password)
            return None  # 密码存储在密钥链，配置文件为空
        except Exception as e:
            raise RuntimeError(f"密钥链保存失败：{e}。请检查密钥链服务是否可用，或重新执行 connect 命令。") from e

    # keyring 不可用但用户提供了密码 → 无法安全存储，必须明确报错
    if use_keyring and not _HAS_KEYRING:
        raise RuntimeError("keyring 库未安装，无法安全存储密码。\n请执行 pip install keyring 安装后重试。")

    # use_keyring=False 时不应走到这里（外部不应手动禁用密钥链）
    return None


def load_password(conn_name: str, conn_config: dict) -> str:
    """加载密码

    Args:
        conn_name: 连接名称
        conn_config: 连接配置字典

    Returns:
        明文密码
    """

    password = ""

    # 1. 尝试从密钥链读取
    if _HAS_KEYRING:
        try:
            password = keyring_module.get_password(_SERVICE_NAME, conn_name)
            if password:
                return password
        except Exception as e:
            warnings.warn(
                f"密钥链读取失败：{e}，尝试从配置文件读取",
                SecurityWarning,
                stacklevel=2,
            )

    # 2. 尝试从配置文件读取（旧格式 - XOR/DPAPI 已废弃）
    #    由于 XOR/DPAPI 加密已移除，旧密码无法解密。
    #    用户需重新执行 `db_tool.py connect` 以使用密钥链存储。
    cipher = conn_config.get("password")
    if cipher:
        print(f"⚠ 连接 '{conn_name}' 使用旧版加密密码，无法解密。")
        print("  请重新执行 connect 命令以使用系统密钥链存储。")

    return ""


def delete_password(conn_name: str, use_keyring: bool = True) -> bool:
    """删除密码

    Args:
        conn_name: 连接名称
        use_keyring: 是否使用密钥链（默认 True）

    Returns:
        是否删除成功
    """

    # 从密钥链删除
    if use_keyring and _HAS_KEYRING:
        try:
            keyring_module.delete_password(_SERVICE_NAME, conn_name)
            return True
        except Exception:
            return False

    return False


def check_security_level(conn_config: dict) -> dict:
    """检查连接安全级别

    Args:
        conn_config: 连接配置字典

    Returns:
        安全级别信息字典
    """
    info = {"level": "UNKNOWN", "method": "UNKNOWN", "secure": False, "warnings": []}

    # 密钥链加密
    if conn_config.get("_keyring_ref"):
        info["level"] = "HIGH"
        info["method"] = "System Keyring"
        info["secure"] = True

        if not _HAS_KEYRING:
            info["warnings"].append("密钥链未安装，密码可能无法读取")

        return info

    # 检查是否使用旧版加密（XOR/DPAPI）
    # 旧版加密代码已移除，仅保留检测逻辑
    if conn_config.get("password") and not conn_config.get("_keyring_ref"):
        info["level"] = "CRITICAL"
        info["method"] = "Legacy Encryption (Unsupported)"
        info["secure"] = False
        info["warnings"].append("使用已废弃的旧版加密存储密码，请重新 connect 以迁移到密钥链")
        return info

    # 无密码（可能使用 Windows 集成认证）
    info["level"] = "INFO"
    info["method"] = "No Password (Integrated Auth)"
    info["secure"] = True
    info["warnings"].append("未存储密码，可能使用 Windows 集成认证")

    return info


def migrate_all_connections(config: dict) -> dict:
    """迁移所有连接到密钥链

    Args:
        config: 配置字典

    Returns:
        更新后的配置字典
    """
    if not _HAS_KEYRING:
        print("⚠ 未安装 keyring 库，无法迁移")
        print("  安装命令: pip install keyring")
        return config

    for name, conn_cfg in config.get("connections", {}).items():
        # 跳过已迁移
        if conn_cfg.get("_keyring_ref"):
            continue

        # 旧版加密密码无法解密，提示用户重新连接
        old_cipher = conn_cfg.get("password")
        if old_cipher:
            print(f"⚠ 连接 '{name}' 使用旧版加密，无法自动迁移。请重新执行 connect 命令。")

    return config


class SecurityWarning(UserWarning):
    """安全警告"""

    pass
