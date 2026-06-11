# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026-2026. All rights reserved

"""OpenJiuwen Runtime Security SDK.

通用安全能力（实现可插拔，调用方仅依赖接口）：

- 加解密：AES-256-GCM（对称）+ X25519 信封（面向公钥的混合加密）。
- 加签验签：Ed25519。
- 证书/密钥管理：密钥与证书的录入、保存、读取、删除（client/server 通用），
  并提供传输无关的握手密钥交换（``KeyExchange`` / server_/client_key_exchange）。

示例：
    from openjiuwen_runtime.management.security import (
        EnvelopeCryptoProvider, Ed25519Signer, Ed25519Verifier,
        CertificateManager, server_key_exchange, client_key_exchange, KeyPurpose,
    )
"""

from .interfaces import (
    ICertificateManager,
    ICryptoProvider,
    ISigner,
    IVerifier,
)
from .models import (
    DEK_ALGORITHM,
    EncAlgorithm,
    KeyPair,
    KeyPurpose,
    PeerKey,
    SealedMessage,
    SECURITY_LOCAL_KEY_TABLE_DEF,
    SECURITY_PEER_KEY_TABLE_DEF,
    SignAlgorithm,
)
from .crypto import EnvelopeCryptoProvider
from .signing import Ed25519Signer, Ed25519Verifier, make_signer, make_verifier
from .certificate import (
    CertificateManager,
    KeyExchange,
    client_key_exchange,
    server_key_exchange,
)

__all__ = (
    # interfaces
    "ICryptoProvider",
    "ISigner",
    "IVerifier",
    "ICertificateManager",
    # models
    "KeyPurpose",
    "SignAlgorithm",
    "EncAlgorithm",
    "DEK_ALGORITHM",
    "KeyPair",
    "PeerKey",
    "SealedMessage",
    "SECURITY_LOCAL_KEY_TABLE_DEF",
    "SECURITY_PEER_KEY_TABLE_DEF",
    # crypto
    "EnvelopeCryptoProvider",
    # signing
    "Ed25519Signer",
    "Ed25519Verifier",
    "make_signer",
    "make_verifier",
    # certificate / key management
    "CertificateManager",
    "KeyExchange",
    "server_key_exchange",
    "client_key_exchange",
)
