# Control de acceso RFID con Raspberry Pi 4B — estado actual y guía de traspaso

**Documento autónomo para continuar el proyecto con otra IA.** Actualizado el 28 de septiembre de 2026. No hace falta conocer la conversación en la que se construyó el sistema: este archivo explica qué hace, cómo está conectado, cómo se ejecuta y dónde está cada parte.

## 1. Qué es el proyecto

Es un prototipo de control de acceso físico. Un lector **RC522** detecta el identificador (UID) de una tarjeta o llavero RFID. Una **Raspberry Pi 4B** compara ese UID con las tarjetas registradas y, según el modo elegido, mueve un **servo SG90** que representa la cerradura. Un **LCD 16×2** muestra mensajes y la cuenta regresiva antes del cierre.

La Pi también ofrece un panel web en la red local. Desde ahí se puede ver el estado en vivo, registrar tarjetas, crear secuencias de tarjetas, elegir el modo de funcionamiento y modificar el tiempo de apertura. El propio panel enlaza un diagrama en otra vista que explica los módulos y procesos.

El montaje actual usa **solo RC522, LCD y servo**. No hay teclado, PIN, pulsadores, LEDs, buzzer, relé ni sensor que confirme la posición real de una puerta.

## 2. Dónde está y cómo acceder

| Recurso | Ubicación |
|---|---|
| Repositorio completo en esta Mac | `/Users/jere/Documents/GitHub/Arquitectura-de-PCs-final` |
| Copia local de la base actual | `/Users/jere/Documents/GitHub/Arquitectura-de-PCs-final/acceso.sqlite3` |
| Copia local independiente del código instalado | `/Users/jere/Documents/GitHub/Arquitectura-de-PCs-final/entrega-rfid-2026-09-28` |
| ZIP de esa copia | `/Users/jere/Documents/GitHub/Arquitectura-de-PCs-final/entrega-rfid-2026-09-28.zip` |
| Código que ejecuta la Pi | `/home/pi/rfid-acceso` |
| SSH de la Pi | `pi@192.168.3.216` (la clave SSH ya está configurada en esta Mac) |
| Panel web | `http://192.168.3.216:5000/` |
| Diagrama web | `http://192.168.3.216:5000/diagrama` |
| Servicio systemd | `acceso-rfid.service` |
| Datos persistentes de la Pi | `/home/pi/rfid-acceso/acceso.sqlite3` |

La **carpeta principal del proyecto** contiene directamente todos los archivos activos: código Python, plantillas, pruebas, `configuracion.json`, `acceso-rfid.service`, `README.md`, este documento y una instantánea de `acceso.sqlite3`. `config-pi/` guarda copias de los archivos del sistema que habilitan SPI e I²C; son referencias para este montaje, no archivos que la aplicación lea desde la Mac. También está `archivo/` con material anterior y respaldos históricos de la Pi; nada de esa carpeta interviene en la aplicación actual. La carpeta `entrega-rfid-2026-09-28` y el ZIP son copias adicionales para compartir, no son necesarias para ver o modificar el proyecto aquí. La dirección IP es la observada en este traspaso; podría cambiar si cambia la red. El servicio está instalado para iniciarse automáticamente al encender la Pi.

## 3. Qué ocurre al presentar una tarjeta

1. `acceso_rfid.py` lee el RC522 aproximadamente cada 50 ms. `rc522_uid_reader.py` valida que la lectura sea completa y devuelve el UID en formato hexadecimal, por ejemplo `30-83-9E-D3`.
2. `controlador_acceso.py` consulta en `padron_rfid.py` si ese UID está registrado y habilitado. También comprueba el modo actual, el bloqueo por fallos, la retirada de la tarjeta y cualquier secuencia en curso.
3. Si corresponde abrir, `servo_puerta.py` envía los pulsos a través del proceso local `pigpiod` hacia GPIO26. El LCD recibe el mensaje desde `lcd_texto_fijo.py` y muestra cuántos segundos faltan para cerrar.
4. `estado_sistema.py` comparte el estado entre el bucle del lector y el servidor web. El navegador consulta `/api/estado` cada segundo para actualizar puerta, lector, tarjeta detectada, bloqueo, modo y último resultado.
5. Al vencer el tiempo, el controlador ordena cerrar el servo. Para iniciar otro intento hay que retirar la tarjeta al menos **1 segundo**. Una tarjeta sostenida sobre el lector no provoca aperturas repetidas.

El estado `ABIERTA` o `CERRADA` de la web describe la **orden enviada al servo**. No existe un sensor que mida la posición de la puerta.

## 4. Los dos modos disponibles

El modo se elige en **Modo de funcionamiento** del panel, se guarda en SQLite y sobrevive a un reinicio. Actualmente está seleccionado **ACCESO**. No existe un tercer modo de «deshabilitado».

### Modo Acceso

Una tarjeta registrada y habilitada abre el servo de inmediato. El LCD muestra `Acceso permitido` y la cuenta regresiva. Mientras dura esa apertura, **se ignoran todas las demás lecturas**, incluso otras tarjetas válidas o inválidas: no extienden el tiempo, no disparan otra apertura y no suman fallos. Al terminar el plazo, el servo vuelve a cerrado.

Las secuencias guardadas en la base **no intervienen** en este modo. Una tarjeta que forma parte de una secuencia funciona como cualquier otra tarjeta habilitada.

### Modo Combinación

Solo puede abrirse mediante una **secuencia completa** de 2 a 8 tarjetas registradas y habilitadas, presentadas en el orden configurado. Una tarjeta suelta no abre, aunque esté habilitada. Cada paso intermedio mantiene el servo cerrado y **no muestra progreso** ni en el LCD ni como evento de secuencia en la web. Al presentar el último paso, el servo abre y el LCD muestra la palabra final elegida para esa secuencia.

Hay que retirar cada tarjeta durante al menos 1 segundo antes de acercar la siguiente. El plazo para el próximo paso es el mismo valor configurable que se usa para mantener la puerta abierta; hoy vale **5 segundos**. Cada paso intermedio correcto reinicia ese plazo privado. Si vence o aparece una tarjeta que no era el siguiente paso, se pierde el progreso. Una tarjeta equivocada que sea el inicio de otra secuencia puede comenzar esa otra secuencia. Durante la apertura después del último paso también se ignoran las lecturas.

Cambiar de modo cancela cualquier secuencia parcial y, si el servo estaba abierto, ordena cerrarlo. Después del cambio se exige retirar la tarjeta antes de aceptar otro intento.

### Reglas comunes

- Un UID **no registrado** muestra `Acceso / incompleto`. Tras **3 presentaciones consecutivas** de UID no registrados, se bloquean las lecturas durante **10 segundos**. El LCD y la web muestran la cuenta regresiva del bloqueo.
- Una tarjeta registrada pero **deshabilitada** no abre y no cuenta como UID desconocido para ese bloqueo.
- Una tarjeta habilitada aceptada reinicia el contador de fallos. Durante la apertura y el bloqueo no se procesan nuevos códigos de acceso.
- El tiempo ajustable desde la página admite de **2 a 60 segundos** y se aplica desde la siguiente lectura; no cambia un plazo que ya empezó.

## 5. Cómo se administran tarjetas y secuencias

**Alta de tarjeta sin saber el UID:** en el panel, sección **Alta de RFID**, pulsar **Leer tarjeta con el sensor**, acercar una sola tarjeta al RC522, retirarla, escribirle un nombre y pulsar **Agregar**. La captura dura como máximo 30 segundos. Esa lectura administrativa no abre el servo ni guarda el UID automáticamente; guardar exige el último paso. También se puede escribir el UID manualmente.

**Padrón:** cada tarjeta tiene nombre, UID y estado habilitada/deshabilitada. La página permite modificarla o eliminarla. Si se elimina una tarjeta usada por una secuencia, se elimina esa secuencia para evitar una combinación incompleta.

**Secuencias:** en **Secuencias RFID** se eligen entre 2 y 8 tarjetas en orden y una palabra final de hasta 16 caracteres que quepa en el LCD. Se pueden crear, editar o borrar. Una misma tarjeta no puede ser el primer paso de dos secuencias distintas, para evitar ambigüedad. Las secuencias configuradas solo tienen efecto en modo **Combinación**.

El panel comunica si un cambio fue aplicado o rechazado. Los formularios de escritura usan un token CSRF generado al iniciar la aplicación. Después de reiniciar el servicio hay que recargar la página antes de guardar cambios.

## 6. Datos concretos guardados ahora

La base de la Pi tenía estos registros al actualizar este documento:

| Tarjeta | UID | Estado |
|---|---|---|
| Llavero 2 | `30-83-9E-D3` | Habilitada |
| Tarjeta amarilla | `50-C8-E4-A4` | Habilitada |
| Tarjeta oscura | `B2-B3-40-30` | Habilitada |

Hay una secuencia llamada **Test**: **Llavero 2 → Tarjeta amarilla**. Su palabra final es **Hola**. La configuración guardada contiene `modo_control=ACCESO` y `tiempo_abierto_s=5`.

`padron_rfid.py` contiene dos UID en la constante `RFID_INICIALES`. **Solo se copian a una base nueva una vez.** En una instalación ya existente, la fuente de verdad es `acceso.sqlite3`: editar esa constante no modifica las tarjetas que ya están en SQLite. La raíz del proyecto y la entrega incluyen una copia consistente de la base de la Pi para reproducir este estado.

## 7. Hardware y cableado

Los números GPIO de esta tabla usan numeración **BCM**; los pines físicos son los del conector de 40 pines de la Pi.

| Dispositivo / señal | GPIO BCM | Pin físico / alimentación |
|---|---:|---|
| RC522 CS | 8 | 24 |
| RC522 SCK | 11 | 23 |
| RC522 MOSI | 10 | 19 |
| RC522 MISO | 9 | 21 |
| RC522 RST | 25 | 22 |
| RC522 VCC | — | 3,3 V |
| LCD PCF8574 SDA | 23 | 16 |
| LCD PCF8574 SCL | 5 | 29 |
| LCD VCC | — | 3,3 V, conexión directa |
| SG90 señal | 26 | 37 |
| SG90 alimentación | — | 5 V |
| Todos los GND | — | GND común |

El LCD usa I²C por software en `/dev/i2c-3`, dirección `0x27`. SPI está habilitado para el RC522. En `/boot/firmware/config.txt` se usa el overlay `i2c-gpio` con SDA 23 y SCL 5; los detalles están en `README.md`. Hay copias de ese archivo y de `/etc/modules-load.d/rfid-i2c.conf` en `config-pi/`. El primero contiene también otras opciones del arranque de la Pi: úsalo como referencia, no lo sobrescribas entero en otro equipo. No alimentar el RC522 a 5 V. El servo necesita una alimentación de 5 V capaz de soportarlo y debe compartir GND con la Pi. No conectar su señal a otro GPIO sin ajustar el código.

## 8. Arquitectura de software

`systemd` inicia **un proceso Python** (`acceso_rfid.py`). Dentro de él, el lector y el controlador funcionan en el hilo principal y Flask atiende la web en otro hilo. Los archivos `.py` siguientes son módulos importados, **no procesos independientes**. `pigpiod` sí es otro proceso local, requerido para generar los pulsos del servo.

```text
Navegador ↔ panel_web.py (Flask, hilo web)
                 ↕                     ↕
        estado_sistema.py         padron_rfid.py ↔ acceso.sqlite3
                 ↕                     ↕
RC522 → rc522_uid_reader.py → acceso_rfid.py → controlador_acceso.py
                                             ├→ lcd_texto_fijo.py → LCD
                                             └→ servo_puerta.py → pigpiod → SG90
```

| Archivo | Responsabilidad principal |
|---|---|
| `acceso_rfid.py` | Lee `configuracion.json`, toma el lock `/tmp/rfid-acceso.lock`, abre los dispositivos, inicia Flask y ejecuta el bucle RFID. |
| `controlador_acceso.py` | Decide según modo, UID y tiempo; gestiona secuencias, fallos, cierre y mensajes. No depende directamente de GPIO, lo que permite probarlo sin hardware. |
| `padron_rfid.py` | Crea y migra SQLite; administra tarjetas, secuencias, modo y tiempo. |
| `estado_sistema.py` | Mantiene el estado en memoria compartido entre ambos hilos y coordina la captura de UID para altas. |
| `panel_web.py` | Rutas Flask, API, validación de formularios y arranque del servidor web en un hilo. |
| `templates/panel.html` | Interfaz y JavaScript del panel; actualiza el estado cada segundo. |
| `templates/diagrama.html` | Explicación visual de procesos y flujo, accesible desde el panel. |
| `rc522_uid_reader.py` | Comunicación SPI con el RC522; detecta errores y valida el UID completo. |
| `lcd_texto_fijo.py` | Escritura del LCD mediante I²C. |
| `servo_puerta.py` | Control del SG90 a través del daemon `pigpiod`. |
| `configuracion.json` | GPIO, pulsos del servo, buses, tiempos iniciales y host/puerto web. |
| `acceso-rfid.service` | Definición systemd instalada en `/etc/systemd/system/`. |
| `tests/` | Pruebas de lógica, base, panel, captura y RC522 sin tocar hardware. |
| `config-pi/` | Copias de la configuración de arranque y carga de I²C de la Pi. |
| `archivo/` | Código descartado, notas y respaldos antiguos; no se ejecuta con el servicio. |

Las rutas HTTP relevantes son `GET /` (panel), `GET /diagrama`, `GET /api/estado`, `GET /api/tarjetas` y rutas `POST` para modo, tiempo, captura, tarjetas y secuencias. El lector físico **solo debe ser usado por la instancia del servicio**; ejecutar otro lector de prueba en paralelo interfiere con él.

## 9. Ejecución, pruebas y despliegue

La Pi usa Raspberry Pi OS Bookworm y Python 3.11. El proyecto utiliza Flask, `spidev`, `lgpio` y `pigpio`, instalados en la Pi. El servicio depende de `pigpiod`. Para inspeccionar el sistema:

```bash
ssh pi@192.168.3.216
cd /home/pi/rfid-acceso
sudo systemctl status acceso-rfid.service
sudo journalctl -u acceso-rfid.service -n 50 --no-pager
python3 acceso_rfid.py --validar-config
python3 -m unittest discover -s tests -v
```

**No ejecutar `python3 acceso_rfid.py` en paralelo con el servicio.** El programa toma un lock exclusivo para evitarlo. Para cambiar el código: trabajar sobre la copia local, ejecutar las pruebas, respaldar la base SQLite de la Pi, copiar solo los archivos modificados a `/home/pi/rfid-acceso`, reiniciar el servicio y verificar `/api/estado` y los logs. No sustituir la base de producción por la base del ZIP si hubo cambios posteriores en la página: la del ZIP es una **instantánea**, no una sincronización permanente.

Comandos de control del servicio:

```bash
sudo systemctl restart acceso-rfid.service
sudo systemctl is-active acceso-rfid.service
```

En esta Mac puede faltar Flask; las **43 pruebas** se ejecutaron correctamente en la Pi durante la última implementación. En este traspaso comprobé que el servicio sigue activo, la API informa lector activo sin error y la puerta figura cerrada. **No se repitió una prueba física acercando tarjetas** al escribir este documento.

## 10. Qué contiene la entrega local

La **raíz** `/Users/jere/Documents/GitHub/Arquitectura-de-PCs-final` contiene todo lo necesario para continuar, dentro del repositorio Git existente. Su archivo `LICENSE` original se conservó. La carpeta `entrega-rfid-2026-09-28` contiene otra copia del código, plantillas, pruebas, configuración, unidad systemd, README, este documento, `acceso.sqlite3`, `config-pi/` y `archivo/`. Los archivos activos y las pruebas se verificaron contra la Pi. Las copias de la base activa fueron creadas con la función de respaldo de SQLite y superaron `PRAGMA integrity_check`. Los otros `.sqlite3` dentro de `archivo/backups-pi/` son respaldos históricos y no son la base activa.

`.gitignore` excluye metadatos de macOS, cachés de Python, bases SQLite con UID reales, respaldos binarios y la carpeta/ZIP de entrega duplicados. **Siguen físicamente en este repositorio local**, pero no aparecerán en un commit ni se publicarán con `git push` salvo que se decida incluirlos expresamente.

El ZIP contiene esa carpeta completa y se puede enviar a otra IA junto con este documento. Incluye los **UID reales** registrados en la base, pero **no contiene claves SSH ni contraseñas**. El archivo `MANIFEST.sha256` permite comprobar los archivos de la copia.

## 11. Límites conocidos y puntos importantes para continuar

- La autorización se basa en UID, que puede clonarse. Es un prototipo y no una cerradura de seguridad certificada.
- La web está disponible en la red local en `0.0.0.0:5000` sin usuario ni contraseña. El CSRF protege formularios frente a solicitudes cruzadas, pero no reemplaza autenticación. No exponer el puerto directamente a Internet.
- No hay sensor de puerta: la web no puede confirmar si el mecanismo se movió. El SG90 deja de recibir pulsos después de cada movimiento y no garantiza fuerza de retención.
- Si se corta la energía o se mata el proceso abruptamente, el software no puede garantizar un cierre mecánico. En salida normal intenta mandar el servo a cerrado.
- El modo y el tiempo de la base tienen prioridad sobre valores iniciales del JSON. La base real de la Pi puede cambiar después de esta instantánea si alguien usa el panel.
- Cualquier cambio en el comportamiento debe respetar el cableado BCM indicado y conservar el padrón SQLite existente. Las pruebas automatizadas no sustituyen una comprobación física con el LCD, el lector y el servo.
