# command_station_app

# 証明書

mkdir -p ~/ssl/private ~/ssl/certs
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
 -keyout ~/ssl/private/prec.key \
 -out ~/ssl/certs/prec.crt
