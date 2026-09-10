# Problemas y soluciones

## La memoria USB no aparecia al arrancar

Se habilito el menu de arranque F12 en la BIOS y se selecciono la entrada UEFI del instalador.

## No bootable device despues de instalar Ubuntu

El firmware InsydeH2O no reconocio automaticamente la entrada de Ubuntu. Se registro como archivo UEFI de confianza el cargador `EFI/ubuntu/shimx64.efi` y el sistema pudo arrancar.

## Error al crear la configuracion de logind

Se creo accidentalmente `/etc/systemd/logind.conf.d` como archivo en vez de directorio. Se hizo una copia temporal, se elimino el archivo y se creo correctamente el directorio con el fichero `10-homelab.conf`.

## La temperatura del mensaje de bienvenida parecia alta

El valor del mensaje de inicio no coincidia con las lecturas directas. `sensors` y `/sys/class/thermal` confirmaron temperaturas normales del procesador en reposo.
