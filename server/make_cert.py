"""Buat sertifikat HTTPS sementara (self-signed) untuk uji coba kamera dari HP di jaringan lokal.

Browser HP hanya mengizinkan kamera lewat HTTPS. Di VPS nanti pakai sertifikat Let's Encrypt
dari aaPanel; sertifikat ini hanya untuk uji coba di laptop.

Pakai:  .venv\\Scripts\\python make_cert.py   -> data/cert.pem dan data/key.pem
"""
import datetime
import ipaddress
import socket

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from app.config import DATA_DIR


def local_ips():
    ips = {"127.0.0.1"}
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ips.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    return sorted(ips)


def main():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "LJK Reader lokal")])
    ips = local_ips()
    san = [x509.DNSName("localhost")] + [x509.IPAddress(ipaddress.ip_address(i)) for i in ips]
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now)
            .not_valid_after(now + datetime.timedelta(days=365))
            .add_extension(x509.SubjectAlternativeName(san), critical=False)
            .sign(key, hashes.SHA256()))
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "key.pem").write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                         serialization.NoEncryption()))
    (DATA_DIR / "cert.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    print("Sertifikat dibuat untuk:", ", ".join(["localhost"] + ips))
    for ip in ips:
        if ip != "127.0.0.1":
            print(f"Buka di HP (satu WiFi dengan laptop): https://{ip}:8443/scan/")


if __name__ == "__main__":
    main()
