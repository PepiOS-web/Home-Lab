# Guia de comandos del HomeLab

Referencia practica para administrar HomeLab Guardian. Los valores entre `< >` son marcadores que deben sustituirse localmente. Nunca deben copiarse contrasenas, claves, direcciones MAC o datos privados al repositorio.

## Distinguir los terminales

```text
PS C:\Users\usuario>       PowerShell de Windows
usuario@homelab:~$         Terminal del servidor Ubuntu
```

Los comandos de PowerShell se ejecutan en el ordenador personal. Los comandos Bash se ejecutan despues de conectarse al servidor.

## Acceso SSH

Conectar mediante el alias configurado en Windows:

```powershell
ssh homelab
```

Conectar indicando usuario e IP:

```powershell
ssh <USUARIO>@<SERVER_IP>
```

Comprobar acceso no interactivo con clave:

```powershell
ssh -o BatchMode=yes -o ConnectTimeout=8 homelab "printf 'SSH_OK'"
```

Activar el agente SSH de Windows desde PowerShell como administrador:

```powershell
Set-Service ssh-agent -StartupType Automatic
Start-Service ssh-agent
Get-Service ssh-agent
```

Cargar la clave desde PowerShell normal:

```powershell
ssh-add "$env:USERPROFILE\.ssh\id_ed25519"
ssh-add -l
```

No publicar la clave privada ni su huella. La clave publica se instala en `~/.ssh/authorized_keys` y debe conservar estos permisos:

```bash
chmod 700 ~/.ssh
chmod 600 ~/.ssh/authorized_keys
```

Diagnosticar un rechazo de clave sin mostrar su contenido:

```bash
sudo journalctl -u ssh --since "5 minutes ago" --no-pager | tail -30
namei -l "$HOME/.ssh/authorized_keys"
```

Cerrar la conexion:

```bash
exit
```

Abrir un tunel temporal hacia un panel que solo escucha en el servidor:

```powershell
ssh -N -L <PUERTO_LOCAL>:127.0.0.1:<PUERTO_SERVIDOR> homelab
```

El tunel permanece activo mientras esa ventana siga abierta. Se cierra con `Ctrl+C`.

## Navegacion por archivos

Mostrar el directorio actual:

```bash
pwd
```

Listar contenido:

```bash
ls
ls -la
```

Entrar en un directorio y volver al anterior:

```bash
cd /srv/data
cd ..
cd ~
```

Rutas importantes:

```text
/home/usuario                  Directorio personal
/srv/data                      HDD de datos persistentes
/srv/data/compose              Archivos Docker Compose
/srv/data/appdata              Datos persistentes de aplicaciones
/srv/data/backups              Copias de seguridad
/srv/data/shared               Archivos compartidos
/etc/netplan                   Configuracion de red
/etc/fstab                     Montajes persistentes
/var/log                       Registros del sistema
```

Mostrar una estructura limitada de directorios:

```bash
find /srv/data -maxdepth 2 -type d
```

Crear directorios:

```bash
mkdir directorio
mkdir -p ruta/directorio
```

Copiar, mover y renombrar:

```bash
cp origen destino
cp -a directorio-origen directorio-destino
mv nombre-anterior nombre-nuevo
```

Eliminar un directorio vacio:

```bash
rmdir directorio
```

> `rm`, especialmente con `-r`, puede borrar datos de forma irreversible. Verificar siempre `pwd`, `ls` y la ruta completa antes de utilizarlo.

## Consultar y editar archivos

Mostrar un archivo:

```bash
cat archivo
less archivo
```

En `less`, usar las flechas para desplazarse y `q` para salir.

Editar con Nano:

```bash
nano archivo
sudo nano /ruta/protegida/archivo
```

En Nano:

```text
Ctrl+O    Guardar
Enter     Confirmar el nombre
Ctrl+X    Salir
Ctrl+W    Buscar
```

Crear una copia antes de modificar una configuracion:

```bash
sudo cp /ruta/configuracion /ruta/configuracion.backup
```

## Informacion del sistema

Version del sistema y kernel:

```bash
cat /etc/os-release
uname -a
```

Tiempo encendido y carga:

```bash
uptime
```

CPU y memoria:

```bash
lscpu
free -h
top
```

Salir de `top` con `q`.

Temperaturas:

```bash
sensors
```

Espacio de almacenamiento:

```bash
df -h
df -h /srv/data
lsblk -f
```

## Red

Mostrar interfaces y direcciones:

```bash
ip -br address
ip -br address show wlp2s0
```

Mostrar rutas:

```bash
ip route
```

Probar acceso a una IP y resolucion DNS:

```bash
ping -c 3 <GATEWAY_IP>
ping -c 3 1.1.1.1
ping -c 3 ubuntu.com
```

Consultar vecinos descubiertos en la red local:

```bash
ip neigh
```

Mostrar puertos TCP y UDP en escucha:

```bash
sudo ss -tulpn
```

Validar y probar cambios de Netplan:

```bash
sudo netplan generate
sudo netplan try
```

`netplan try` revierte los cambios si no se confirman antes de finalizar la cuenta atras. Los cambios de IP deben prepararse preferiblemente desde la consola fisica.

## Servicios y registros

Consultar si un servicio esta activo y habilitado al arrancar:

```bash
systemctl is-active <SERVICIO>
systemctl is-enabled <SERVICIO>
```

Ver informacion detallada:

```bash
sudo systemctl status <SERVICIO>
```

Iniciar, detener y reiniciar:

```bash
sudo systemctl start <SERVICIO>
sudo systemctl stop <SERVICIO>
sudo systemctl restart <SERVICIO>
```

Consultar registros recientes:

```bash
sudo journalctl -u <SERVICIO> -n 50 --no-pager
sudo journalctl -u <SERVICIO> -f
```

`-f` sigue los registros en tiempo real y se detiene con `Ctrl+C`.

## Firewall UFW

Consultar reglas:

```bash
sudo ufw status verbose
sudo ufw status numbered
```

Permitir SSH:

```bash
sudo ufw allow OpenSSH
```

Permitir un puerto solo desde la red local:

```bash
sudo ufw allow from <LAN_CIDR> to any port <PUERTO> proto tcp
```

No abrir paneles directamente a Internet. Docker puede gestionar reglas de red que requieren una revision adicional a UFW.

## Discos y montajes

Identificar discos, modelos y puntos de montaje:

```bash
lsblk -o NAME,SIZE,MODEL,FSTYPE,MOUNTPOINTS
findmnt /srv/data
```

Consultar salud SMART:

```bash
sudo smartctl -a /dev/<DISCO>
sudo smartctl -l selftest /dev/<DISCO>
```

Iniciar pruebas SMART:

```bash
sudo smartctl -t short /dev/<DISCO>
sudo smartctl -t long /dev/<DISCO>
```

> Operaciones como `mkfs`, `wipefs`, `fdisk` o `parted` pueden destruir datos. No ejecutarlas sin comprobar previamente modelo, tamano, montaje y dispositivo exactos.

## Docker

Comprobar Docker y Compose:

```bash
sudo systemctl is-active docker
sudo systemctl is-enabled docker
sudo docker --version
sudo docker compose version
```

Listar contenedores activos o todos:

```bash
sudo docker ps
sudo docker ps -a
```

Ver registros:

```bash
sudo docker logs --tail 50 <CONTENEDOR>
sudo docker logs -f <CONTENEDOR>
```

Consultar salud de un contenedor:

```bash
sudo docker inspect --format '{{.State.Health.Status}}' <CONTENEDOR>
```

Validar un archivo Compose:

```bash
sudo docker compose -f /ruta/compose.yaml config
```

Crear o actualizar un servicio:

```bash
sudo docker compose -f /ruta/compose.yaml up -d
```

Detener una composicion conservando sus datos persistentes:

```bash
sudo docker compose -f /ruta/compose.yaml down
```

Reiniciar un contenedor:

```bash
sudo docker restart <CONTENEDOR>
```

Mostrar nombre y estado de todos los contenedores activos:

```bash
sudo docker ps --format 'table {{.Names}}\t{{.Status}}'
```

Uso de recursos:

```bash
sudo docker stats
sudo docker system df
```

Salir de `docker stats` con `Ctrl+C`.

## Servicios actuales

Uptime Kuma:

```bash
sudo docker inspect --format '{{.State.Health.Status}}' uptime-kuma
sudo docker logs --tail 50 uptime-kuma
sudo docker compose -f /srv/data/compose/uptime-kuma/compose.yaml up -d
```

NetAlertX:

```bash
sudo docker inspect --format '{{.State.Health.Status}}' netalertx
sudo docker logs --tail 50 netalertx
sudo docker compose -f /srv/data/compose/netalertx/compose.yaml up -d
```

Homepage:

```bash
sudo docker restart homepage
sudo docker logs --since 2m homepage
sudo nano /srv/data/appdata/homepage/settings.yaml
sudo nano /srv/data/appdata/homepage/services.yaml
sudo nano /srv/data/appdata/homepage/custom.css
sudo nano /srv/data/appdata/homepage/custom.js
```

Grafana y Prometheus:

```bash
sudo docker compose -f /srv/data/compose/monitoring/compose.yaml config --quiet
sudo docker compose -f /srv/data/compose/monitoring/compose.yaml up -d --force-recreate grafana
sudo docker logs --tail 50 grafana
```

Comprobar la configuracion efectiva de Grafana sin mostrar secretos:

```bash
sudo docker inspect grafana \
  --format '{{range .Config.Env}}{{println .}}{{end}}' |
grep -E '^GF_SERVER_(DOMAIN|ROOT_URL|SERVE_FROM_SUB_PATH|ENFORCE_DOMAIN)='
```

Grafana se publica bajo `https://portal.home.arpa/grafana/`. Al compartir origen con Homepage, el panel autenticado funciona en navegadores moviles sin habilitar acceso anonimo.

Validar y recargar Caddy:

```bash
sudo docker exec caddy \
  caddy validate \
  --config /etc/caddy/Caddyfile \
  --adapter caddyfile

sudo docker exec caddy \
  caddy reload \
  --config /etc/caddy/Caddyfile \
  --adapter caddyfile
```

Probar una ruta HTTPS cuando el DNS local no esta disponible en el propio servidor:

```bash
curl -ksSI \
  --resolve portal.home.arpa:443:<SERVER_IP> \
  https://portal.home.arpa/grafana/login |
head
```

Una respuesta `HTTP/2 200` confirma que Caddy alcanza Grafana en la subruta.

## Copias de seguridad del servidor

Consultar el temporizador y ejecutar una copia manual:

```bash
systemctl status homelab-backup.timer --no-pager
systemctl list-timers --all | grep homelab-backup
sudo systemctl start homelab-backup.service
```

Verificar el resultado:

```bash
systemctl status homelab-backup.service --no-pager
sudo journalctl -u homelab-backup.service -n 40 --no-pager
sudo ls -lh /srv/data/backups/daily
```

El servicio es `oneshot`: `inactive (dead)` es normal despues de finalizar. El resultado valido es `status=0/SUCCESS` y la suma debe indicar `OK`.

Verificar manualmente la suma del ultimo backup:

```bash
cd /srv/data/backups/daily
latest=$(find . -maxdepth 1 -type f -name 'homelab-*.tar.gz' -printf '%T@ %f\n' | sort -nr | awk 'NR == 1 { print $2 }')
sudo sha256sum -c "${latest}.sha256"
```

## Copia externa cifrada en Windows

La copia externa usa `restic`. El servidor conserva copias diarias y el ordenador obtiene una copia semanal cifrada. Los archivos sin cifrar se descargan solo a un directorio temporal fuera de OneDrive y se eliminan al finalizar.

Ejecutar manualmente la copia externa:

```powershell
powershell.exe `
  -NoProfile `
  -ExecutionPolicy Bypass `
  -File "$env:USERPROFILE\OneDrive\Desktop\HomeLab-Backups\Backup-HomeLab.ps1"
```

Consultar la tarea semanal:

```powershell
Get-ScheduledTask -TaskName "HomeLab Encrypted Backup"
Get-ScheduledTaskInfo -TaskName "HomeLab Encrypted Backup"
```

Ejecutarla inmediatamente y consultar el resultado:

```powershell
Start-ScheduledTask -TaskName "HomeLab Encrypted Backup"
Get-ScheduledTaskInfo -TaskName "HomeLab Encrypted Backup"
```

`LastTaskResult` igual a `0` indica exito. La tarea esta programada semanalmente y usa `StartWhenAvailable` para ejecutarse despues si el ordenador no estaba disponible.

Comprobar que no quedaron archivos temporales sin cifrar:

```powershell
Get-ChildItem "$env:LOCALAPPDATA\HomeLabBackup\staging" -Force
```

La contrasena original de `restic` debe guardarse en un gestor de contrasenas. El archivo DPAPI permite automatizar el proceso solo con el mismo usuario de Windows, pero no sustituye la contrasena para una recuperacion en otro equipo.

## Restauracion de prueba

Una copia no se considera verificada hasta demostrar que puede restaurarse. La prueba debe hacerse en una carpeta temporal y nunca sobre el servidor activo.

Despues de restaurar el ultimo snapshot con `restic`, comprobar el archivo:

```powershell
tar -tzf "<RUTA_TEMPORAL>\homelab-<FECHA>.tar.gz" |
Select-String "srv/data/compose|srv/data/appdata/homepage|etc/ssh"
```

Antes de borrar la prueba, resolver y revisar la ruta exacta:

```powershell
$target = [IO.Path]::GetFullPath("$env:LOCALAPPDATA\HomeLabRestoreTest-current")
$target
```

Solo si coincide exactamente con la carpeta temporal esperada:

```powershell
Remove-Item -LiteralPath "$env:LOCALAPPDATA\HomeLabRestoreTest-current" -Recurse -Force
```

No borrar ni mover la carpeta `repository` de OneDrive: contiene el repositorio cifrado real.

## Actualizaciones

Actualizar Ubuntu:

```bash
sudo apt update
sudo apt upgrade
```

Antes de actualizar contenedores persistentes se debe realizar una copia de seguridad. El flujo general es:

```bash
sudo docker compose -f /ruta/compose.yaml pull
sudo docker compose -f /ruta/compose.yaml up -d
```

No automatizar actualizaciones de versiones principales sin revisar notas de cambios y copias de seguridad.

## Apagar y reiniciar

```bash
sudo reboot
sudo poweroff
```

`poweroff` requiere volver a encender fisicamente el portatil, salvo que se configure y soporte Wake-on-LAN.

## Comprobacion rapida del HomeLab

```bash
ip -br address
ip route
findmnt /srv/data
df -h /srv/data
sudo ufw status
sudo docker ps
sensors
```

Estos comandos permiten revisar red, almacenamiento, firewall, contenedores y temperaturas sin modificar el sistema.
