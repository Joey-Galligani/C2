# Server C2 Documentation

## Setup C2

### Required :
```bash
mkdir Keys
ssh-keygen -t ed25519 -f server_key
mv server_key* Keys
```

copy your public or client pub key into authorized_keys file :
```bash
ssh-ed25519 AAAA... client
```

## Run the server (backend and frontend)

```bash
./install.sh
cd src/backend && sudo python3 main.py
cd src/frontend && npm run start
```

open the browser and go to http://localhost:3000
