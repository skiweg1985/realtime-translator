#!/bin/sh
set -eu
cd "$(dirname "$0")"
APP_IP=${1:?Usage: ./setup-certs.sh LAN_IP [hostname.local]}
APP_HOST=${2:-localhost}
mkdir -p certs
umask 077
if [ ! -f certs/ca.key ]; then
 openssl req -x509 -newkey rsa:3072 -nodes -keyout certs/ca.key -out certs/ca.crt -days 365 -subj '/CN=Translate Local Development CA' -addext 'basicConstraints=critical,CA:TRUE' -addext 'keyUsage=critical,keyCertSign,cRLSign'
fi
openssl req -newkey rsa:2048 -nodes -keyout certs/server.key -out certs/server.csr -subj '/CN=Translate Local'
printf 'subjectAltName=DNS:localhost,DNS:%s,IP:127.0.0.1,IP:%s\nbasicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\n' "$APP_HOST" "$APP_IP" > certs/server.ext
openssl x509 -req -in certs/server.csr -CA certs/ca.crt -CAkey certs/ca.key -CAcreateserial -out certs/server.crt -days 90 -sha256 -extfile certs/server.ext
cat certs/server.crt certs/server.key > certs/server.pem
openssl x509 -in certs/ca.crt -outform der -out frontend/public/local-ca.cer
chmod 644 certs/server.pem frontend/public/local-ca.cer
