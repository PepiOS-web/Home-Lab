# Instalacion inicial - 10 de septiembre de 2026

## Trabajo realizado

1. Se identificaron los componentes del portatil reutilizado.
2. Se creo una memoria USB e instalo Ubuntu Server 24.04 LTS en el SSD.
3. Se corrigio el arranque UEFI desde la BIOS Acer InsydeH2O.
4. Se verificaron el SSD del sistema y el HDD secundario.
5. Se configuro la interfaz Wi-Fi y se comprobo la conectividad.
6. Se establecio acceso SSH desde Windows.
7. Se creo una clave Ed25519 protegida por frase de paso.
8. Se activo UFW permitiendo solo OpenSSH.
9. Se desactivaron suspension, hibernacion y la accion de cierre de tapa.
10. Se iniciaron pruebas SMART extendidas en ambos discos.

## Aprendizajes

- Diferencia entre BIOS/UEFI, gestor de arranque y sistema operativo.
- Funcionamiento basico de SSH y autenticacion de clave publica.
- Principio de minimo acceso aplicado mediante firewall.
- Configuracion modular de systemd mediante archivos `drop-in`.
- Uso de SMART para evaluar discos antes de almacenar datos.

## Siguiente paso

Revisar el resultado de las pruebas SMART. Si el HDD esta sano, prepararlo con un sistema de archivos Linux y un montaje persistente.
