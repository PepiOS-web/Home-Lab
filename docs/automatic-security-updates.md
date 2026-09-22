# Actualizaciones automaticas de seguridad

## Objetivo

Aplicar automaticamente las correcciones de seguridad permitidas de Ubuntu sin provocar reinicios inesperados ni actualizar de forma desatendida componentes criticos del HomeLab.

## Configuracion

Ubuntu utiliza los temporizadores oficiales `apt-daily.timer` y `apt-daily-upgrade.timer`. La politica adicional se guarda en `/etc/apt/apt.conf.d/52-homelab-unattended-upgrades` y su plantilla publica esta en [`infrastructure/apt/52-homelab-unattended-upgrades`](../infrastructure/apt/52-homelab-unattended-upgrades).

La configuracion:

- mantiene activadas las actualizaciones desatendidas;
- permite los origenes base y de seguridad configurados por Ubuntu;
- excluye `updates`, `proposed`, `backports` y repositorios de terceros;
- bloquea adicionalmente Docker, Containerd y Tailscale;
- desactiva los reinicios automaticos;
- no elimina kernels ni dependencias automaticamente;
- registra la actividad mediante syslog.

Docker y Tailscale se actualizan manualmente despues de crear y verificar un backup. Tras cada actualizacion se comprueban los servicios, contenedores, firewall, rutas privadas, DNS, HTTPS y SSH.

## Verificacion

```bash
systemctl is-enabled apt-daily.timer apt-daily-upgrade.timer
systemctl is-active apt-daily.timer apt-daily-upgrade.timer

sudo apt-config dump | grep -E \
  'Automatic-Reboot|Remove-Unused|SyslogEnable|DevRelease|Package-Blacklist'

sudo unattended-upgrade --dry-run --debug
```

La simulacion debe mostrar unicamente los origenes autorizados. Los repositorios de Docker y Tailscale deben aparecer como no permitidos y no debe aparecer ningun `ERROR`.

## Registros

```bash
sudo journalctl -u apt-daily-upgrade.service --no-pager
sudo less /var/log/unattended-upgrades/unattended-upgrades.log
```

Un archivo `/var/run/reboot-required` indica que una actualizacion requiere un reinicio manual. La politica nunca lo ejecuta por si sola.

## Recuperacion

La configuracion forma parte del backup consistente. Para desactivar temporalmente la automatizacion sin borrar archivos:

```bash
sudo systemctl disable --now apt-daily.timer apt-daily-upgrade.timer
```

Para volver a activarla:

```bash
sudo systemctl enable --now apt-daily.timer apt-daily-upgrade.timer
```
