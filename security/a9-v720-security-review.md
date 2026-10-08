# Revisión de seguridad de `intx82/a9-v720`

Fecha de revisión: 2026-09-30

## Alcance y resultado

Se revisó estáticamente la rama `master` del repositorio
[`intx82/a9-v720`](https://github.com/intx82/a9-v720), sin ejecutar su código ni
instalar sus APK.

- Commit auditado: `a795f8b4e17a03394d66cdde1d2633dd08e6be87`
- Fecha del commit: 2025-12-19
- SHA-256 del ZIP descargado:
  `3CD5E4453018615FEE58C06C3D931193CFB6BA68B27DC0A9E2F410AB6CE14DB4`
- Cámara prevista: Nax/V720, serie `0800c0027DC3`, firmware `202305301050`

**Conclusión:** no se ha encontrado una puerta trasera intencionada evidente en
el código Python revisado. Sin embargo, el proyecto **no debe desplegarse tal
como está**: expone vídeo y audio sin autenticación, escucha en interfaces de
red más amplias de lo que indica su texto de ayuda, utiliza protocolos sin
cifrado y fija dependencias antiguas con vulnerabilidades conocidas. La ausencia
de indicios no demuestra la ausencia absoluta de una puerta trasera, y los APK
binarios incluidos quedan fuera de confianza.

## Qué hace realmente el proyecto

El programa implementa por ingeniería inversa parte del protocolo de estas
cámaras. Tiene dos usos principales:

1. En modo AP, se conecta directamente a la cámara en `la dirección IP predeterminada de la cámara:6123`.
2. En modo STA, suplanta localmente parte de la nube Naxclow y recibe las
   conexiones de la cámara mediante HTTP, TCP, UDP y MQTT.

El servidor falso abre TCP y UDP en el puerto `6123`, un servidor HTTP
configurable (por defecto, puerto `80`) y puertos UDP dinámicos entre `32768` y
`65534`. Ofrece rutas como:

- `/dev/list`
- `/dev/<id>/live`
- `/dev/<id>/video`
- `/dev/<id>/audio`
- `/dev/<id>/snapshot`

También responde a rutas que la cámara utiliza para registrar y configurar el
servidor Naxclow. El diseño requiere que nombres como `v720.naxclow.com` y
`v720.p2p.naxclow.com` se resuelvan hacia el servidor local.

## Hallazgos

### Críticos antes del despliegue

1. **Vídeo y audio sin autenticación.** Las rutas de streaming y captura no
   comprueban usuario, contraseña, token de sesión ni autorización. Cualquier
   dispositivo que alcance el puerto HTTP podría ver la imagen, escuchar el
   audio o enumerar cámaras.

2. **El HTTP escucha en todas las interfaces.** `v720_http.py` crea
   `ThreadingHTTPServer(("", puerto), ...)`. La cadena vacía equivale a todas
   las interfaces IPv4, aunque el programa anuncia enlaces `127.0.0.1`. Es una
   discrepancia de seguridad entre la interfaz real y la documentación.

3. **Protocolos sin cifrado ni identidad fuerte.** El tráfico de cámara utiliza
   HTTP, MQTT, TCP y UDP sin TLS. Hay tokens y contraseñas de protocolo que se
   registran en modo de depuración. Un cliente presente en la misma red podría
   observar, reproducir o falsificar tráfico.

4. **Dependencias vulnerables.** Una consulta a OSV para las versiones fijadas
   detectó avisos en `opencv-python==4.8.0.76`, `Pillow==9.5.0` y
   `tqdm==4.64.0`. Pillow 9.5.0 acumula avisos de ejecución de código, escrituras
   fuera de límites y denegación de servicio. Esto es especialmente relevante
   porque el proceso interpreta imágenes procedentes de una cámara no fiable.

### Riesgo alto o medio

5. **Superficie de red amplia.** El servicio acepta conexiones TCP/UDP en
   `6123` y abre un puerto UDP aleatorio alto. Sin reglas de firewall estrictas,
   otros equipos de la LAN pueden enviar datos al parser de protocolo.

6. **MQTT local insuficientemente definido.** La documentación llega a sugerir
   redirigir hacia un broker público. Eso no es aceptable para este despliegue.
   Un broker local debe impedir acceso anónimo, escuchar solamente en la red
   aislada y no exponerse a Internet.

7. **Uso sugerido del puerto privilegiado 80.** La documentación propone
   ejecutar con permisos elevados o rebajar globalmente el inicio de puertos no
   privilegiados. Debe usarse un puerto alto y un usuario sin privilegios.

8. **APK y artefactos binarios incluidos.** El repositorio contiene dos APK, un
   ZIP de código decompilado y capturas de tráfico. La descarga completa ocupa
   aproximadamente 99 MB. Esos APK no son necesarios para el servidor y no se
   han podido considerar confiables mediante esta revisión del código Python.

9. **Sin licencia visible.** No se encontró un archivo `LICENSE` en el commit
   revisado. Aunque el código sea público, eso no concede automáticamente
   permiso para redistribuir una versión modificada.

10. **Madurez limitada.** No hay pruebas automatizadas, empaquetado, imagen de
    contenedor ni flujo CI visible. Existe además un archivo duplicado
    `fake_srv copy.py`. Esto aumenta el coste de mantenimiento y auditoría.

### Lo que no se encontró en el código Python

- No hay llamadas activas a `subprocess`, `os.system`, `eval`, `exec` o shell.
- No hay descarga de código o actualización automática.
- No hay instalación de servicios, tareas programadas, claves SSH o
  persistencia del sistema.
- No hay acceso al socket Docker ni exploración explícita de archivos del host.
- No hay dominios externos codificados en el flujo Python salvo los nombres
  Naxclow que el servidor pretende suplantar localmente.

Estos puntos reducen la sospecha de malware deliberado, pero no eliminan los
fallos de exposición de red ni los riesgos de la cámara y sus formatos de entrada.

## Condiciones mínimas para aprobar un despliegue

1. Usar solamente un fork propio del commit auditado. No desplegar `master`
   mutable ni actualizar automáticamente.
2. Excluir `orig-app/`, `docs/`, capturas, APK y cualquier código duplicado de la
   imagen de ejecución.
3. Actualizar dependencias, fijarlas por versión y hash y repetir el escaneo de
   vulnerabilidades antes de construir.
4. Modificar el HTTP para escuchar solo en `127.0.0.1` o en una interfaz interna
   dedicada. Nunca en `0.0.0.0` sobre la LAN doméstica.
5. Ejecutar como usuario sin privilegios, en puerto alto, con sistema de archivos
   de solo lectura, `no-new-privileges`, todas las capabilities eliminadas y
   límites de memoria, CPU, procesos y tamaño de petición.
6. Publicar la vista únicamente mediante Caddy con HTTPS y autenticación, o por
   Tailscale. No crear redirecciones de puertos en el router.
7. Mantener MQTT local, con acceso anónimo desactivado y reglas por tópico. No
   usar brokers públicos.
8. Colocar la cámara en una red IoT/SSID/VLAN aislada. Bloquear por defecto todo
   tráfico de la cámara hacia Internet y hacia la LAN.
9. Permitir únicamente cámara -> HomeLab en los puertos exactos necesarios y
   HomeLab -> cámara si el protocolo lo exige. Bloquear cámara -> otros clientes.
10. Desactivar UPnP y WPS. Reservar por DHCP la IP de la cámara y verificar su MAC.
11. Evitar logs de depuración permanentes, porque el código registra tokens y
    datos de protocolo.
12. Capturar y revisar tráfico durante las pruebas para demostrar que no existe
    salida WAN ni resolución DNS fuera del servidor local.

## Revisión pendiente del router

Antes de conectar la cámara a la red doméstica hay que comprobar en el router:

- reserva DHCP por MAC;
- bloqueo de Internet por dispositivo o, preferiblemente, VLAN/ACL;
- UPnP y WPS desactivados;
- aislamiento de clientes o red de invitados/IoT;
- posibilidad de permitir una excepción exclusiva entre cámara y HomeLab;
- ausencia de port-forwarding y administración remota desde Internet;
- DNS asignado a la cámara y capacidad de sobrescribir los dominios Naxclow.

Si el router no permite una regla del tipo «cámara sin Internet, sin acceso a la
LAN y solamente accesible desde HomeLab», una contraseña Wi-Fi fuerte por sí
sola no proporciona el aislamiento requerido. En ese caso hará falta una VLAN,
un punto de acceso IoT separado o una segunda interfaz Wi-Fi dedicada al servidor.

## Decisión actual

**NO-GO para instalar el repositorio original directamente.**

**GO condicionado** para construir una variante mínima y endurecida después de
confirmar las capacidades del router, actualizar dependencias, corregir el bind
HTTP y verificar mediante captura de tráfico que la cámara no sale a Internet.

## Implementación local iniciada

La preparación reproducible y el parche endurecido están en
`infrastructure/docker/a9-v720-hardened/`. El repositorio HomeLab no almacena el
código de terceros: el script descarga el commit auditado, valida su SHA-256,
extrae solo el código necesario y aplica el parche local.

Se ha verificado que el parche se aplica limpiamente, que los módulos Python
modificados compilan y que las comprobaciones de autenticación y lista blanca de
IP aceptan las credenciales/dirección correctas y rechazan las incorrectas.

El servicio no debe arrancarse todavía. Faltan la reserva DHCP, el aislamiento
del router, las reglas UFW, los hosts DNS locales y las rutas Caddy.
