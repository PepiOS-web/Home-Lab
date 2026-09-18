# 2026-09-18 - DNS local con AdGuard Home

Se desplego AdGuard Home como resolver DNS local y filtro de dominios. El servicio publica DNS 53 TCP/UDP solo en la direccion privada del servidor, mientras que su panel administrativo permanece en loopback detras de Caddy y HTTPS interno.

Se crearon rewrites para los paneles `*.home.arpa` y se validaron tanto la resolucion local como la de dominios externos. Un ordenador y un telefono se configuraron manualmente como clientes antes de considerar un cambio en el DHCP del router.

Uptime Kuma incorpora un monitor DNS que comprueba cada minuto un registro A local. La prueba mostro el servicio disponible y la respuesta esperada. AdGuard Home tambien se anadio al ciclo consistente de parada, copia y reinicio del backup diario; la ejecucion manual termino correctamente y todos los contenedores regresaron a estado operativo.

No se publican direcciones reales, historiales DNS, credenciales, certificados privados ni claves de la autoridad interna.
