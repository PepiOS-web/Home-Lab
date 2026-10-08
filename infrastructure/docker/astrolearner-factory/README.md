# AstroLearner Factory

MVP local para convertir fuentes científicas verificables en un borrador de
vídeo de AstroLearner. No utiliza APIs de IA de pago y no publica contenido.

## Alcance de esta primera versión

El flujo implementado es:

```text
tema + 1-5 fuentes permitidas
        |
        v
captura de fuentes -> guion JSON mediante Ollama -> revisión humana
        |
        v
Piper TTS -> ilustraciones Pillow + música original -> vídeo + 3 Shorts + SRT
        |
        v
revisión humana -> borrador aprobado (sin subida ni publicación)
```

Componentes:

- Ollama local con `qwen3.5:4b-q4_K_M`.
- FastAPI y SQLite para el panel, cola secuencial y trazabilidad.
- Piper con la voz española `es_ES-davefx-medium`.
- FFmpeg y Pillow para generar ilustraciones científicas originales, música
  ambiental procedural, el vídeo 16:9, tres Shorts 9:16 con ángulos distintos,
  subtítulos y miniatura.

La aplicación descarga únicamente páginas HTTPS de una lista explícita de
dominios científicos. Trata todo el texto descargado como datos no fiables y
no como instrucciones. El render no descarga fotos ni música de terceros:
elige un renderizador cerrado (fases lunares, órbitas, eclipses, planetas,
estrellas, galaxias, telescopios o escalas) y genera tanto la ilustración como
la música dentro del contenedor. Los esquemas no pretenden estar a escala.

## Recursos y privacidad

- Interfaz enlazada solo a `127.0.0.1:8090`.
- Formularios protegidos con token anti-CSRF y cabeceras de navegador
  restrictivas.
- Ollama no publica ningún puerto y tiene desactivadas las funciones cloud.
- Un único trabajo se procesa a la vez.
- Ollama se limita a 5 GiB y descarga el modelo de memoria tras la doble pasada.
- Cada borrador pasa por una segunda revisión local que corrige contradicciones,
  términos impropios y afirmaciones sin respaldo antes de mostrarse.
- El estudio se limita a 2 GiB y cuatro CPU lógicas.
- Datos persistentes: `/srv/data/appdata/astrolearner`.
- No hay claves, credenciales ni tokens en el repositorio.
- Un reinicio marca los trabajos interrumpidos como fallidos para que puedan
  reintentarse en lugar de quedar bloqueados.

La imagen de Ollama está fijada al manifiesto Linux/amd64 que fue auditado al
crear este MVP. Las actualizaciones deben probarse de forma explícita.

## Instalación controlada

Copiar el directorio a `/srv/data/compose/astrolearner-factory` y ejecutar:

```bash
cd /srv/data/compose/astrolearner-factory
cp .env.example .env
chmod 600 .env
./scripts/doctor.sh
sudo ./scripts/bootstrap.sh
```

`doctor.sh` es de solo lectura. `bootstrap.sh` crea exclusivamente los
directorios de AstroLearner, construye la imagen local, descarga el modelo y la
voz, y levanta los dos contenedores.

Para abrir el panel desde Windows sin modificar Caddy o DNS:

```powershell
ssh -L 8090:127.0.0.1:8090 homelab
```

Mientras esa sesión permanezca abierta, visitar
`http://127.0.0.1:8090` en el navegador.

## Uso

1. Introducir un tema concreto y entre una y cinco URLs permitidas.
2. Esperar la generación local. En CPU puede tardar varios minutos.
3. Contrastar manualmente cada afirmación con las fuentes mostradas.
4. Corregir títulos, narración, descripción o advertencias desde el editor.
5. Aprobar el guion para iniciar el TTS y render, o rechazarlo sin borrar la
   trazabilidad.
6. Ver completos el vídeo y los tres Shorts antes de aprobar el borrador.
7. Si se actualiza el motor visual o la mezcla, usar `Volver a renderizar` sin
   regenerar el guion.

Estados principales:

```text
queued -> processing -> script_ready -> queued -> processing
       -> review_required -> approved
```

Un error deja el trabajo en `failed` y permite reintentar la etapa. La base de
datos utiliza WAL y los artefactos se escriben dentro del directorio UUID de
cada trabajo.

## Operación

```bash
sudo docker compose ps
sudo docker compose logs --tail=100 studio
sudo docker compose logs --tail=100 ollama
./scripts/smoke-test.sh
sudo docker compose stop
```

Para eliminar solo los contenedores conservando modelos y trabajos:

```bash
sudo docker compose down
```

No ejecutar `down --volumes` ni borrar `/srv/data/appdata/astrolearner` si se
quieren conservar los resultados.

## Licencias y uso comercial

- Qwen3.5 se distribuye bajo Apache-2.0 según su ficha oficial.
- Piper se ejecuta como dependencia GPL-3.0.
- La ficha de `es_ES-davefx-medium` declara CC0 para el dataset de voz.
- Las ilustraciones y la música de esta versión son originales y se generan
  localmente. `licenses.json` registra el renderizador, la semilla de la música
  y confirma que no se usaron activos de terceros.

Antes de una publicación real siguen siendo obligatorias la revisión humana de
diagramas, voz, mezcla y subtítulos, las pruebas de originalidad, OAuth de
YouTube y una primera subida privada. La publicación pública seguirá siendo
una acción humana.
