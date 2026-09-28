# Demo de acceso: RFID, LCD y servo

El hardware usa exclusivamente RC522, display LCD 16×2 con backpack PCF8574 y servo SG90 en GPIO26.
Flask sirve el panel y SQLite guarda su padrón.

## Funcionamiento

1. La primera ejecución carga dos llaveros definidos en `RFID_INICIALES`, dentro de `padron_rfid.py`.
2. Al iniciar, el servo va a cerrado y el LCD muestra `Acerque tarjeta`.
3. En modo **acceso**, un UID habilitado muestra `Acceso permitido` y mueve el servo a abierto. Mientras esté abierto, se ignoran todas las lecturas y no se extiende el plazo.
4. Transcurrido el tiempo configurado (5 s por defecto) desde terminar la apertura, el servo vuelve a cerrado.
5. Hay que retirar la tarjeta al menos 1 s antes de aceptar otro ciclo.
6. Un UID desconocido muestra `Acceso / incompleto` sin abrir.
7. El panel web muestra el estado y permite administrar el padrón persistente.
8. Tres presentaciones de UID no registrados bloquean el acceso durante 10 s. Una tarjeta autorizada reinicia el contador de fallos. Durante el bloqueo no se abre el servo.
9. En modo **combinación**, solo se aceptan secuencias ordenadas de 2 a 8 tarjetas. Los pasos intermedios no abren ni revelan avance en LCD o web. La última tarjeta abre y muestra la palabra final. Cada paso correcto renueva el plazo de espera configurado; una tarjeta distinta o un plazo vencido reinicia la secuencia sin abrir.
10. La página y el LCD muestran la cuenta regresiva hasta el cierre del servo. También se muestra el tiempo restante de bloqueo.
11. Los dos modos se eligen desde la página y se guardan en SQLite. Cambiar de modo cancela una secuencia pendiente y cierra una apertura en curso. No hay modo deshabilitado.

El UID es clonable y se transmite en claro. Esta demo autoriza por coincidencia
con una lista, no ofrece autenticación criptográfica ni protección por PIN.
El registro guarda solo el UID en SQLite: no modifica la memoria del llavero.

## Archivos para leer el código

| Archivo | Responsabilidad |
|---|---|
| `acceso_rfid.py` | Programa principal, configuración y cierre de recursos |
| `controlador_acceso.py` | Autorización, temporización y estados |
| `servo_puerta.py` | Pulsos estables con pigpio en BCM26 |
| `padron_rfid.py` | UID iniciales hardcodeados y padrón SQLite editable |
| `panel_web.py` y `templates/` | Estado en vivo y altas, modificaciones y bajas |
| `templates/diagrama.html` | Diagrama de procesos y recorrido de lecturas, accesible desde el panel |
| `estado_sistema.py` | Estado compartido y seguro entre hardware y web |
| `configuracion.json` | Pulsos, tiempos y servidor web |
| `rc522_uid_reader.py` | Driver RC522 con spidev + lgpio |
| `lcd_texto_fijo.py` | Driver LCD I2C y prueba independiente |
| `tests/` | Pruebas sin hardware |
| `archivo/` | Material anterior, fuera de la aplicación actual |

## Cableado definitivo

Los números GPIO son BCM.

| Dispositivo / señal | BCM | Pin físico / alimentación |
|---|---:|---|
| RC522 CS | 8 | 24 |
| RC522 SCK | 11 | 23 |
| RC522 MOSI | 10 | 19 |
| RC522 MISO | 9 | 21 |
| RC522 RST | 25 | 22 |
| RC522 VCC | — | 3,3 V, nunca 5 V |
| LCD SDA | 23 | 16 |
| LCD SCL | 5 | 29 |
| LCD VCC | — | 3,3 V, conexión directa sin divisores |
| Servo señal | **26** | **37** |
| Servo VCC | — | 5 V, fuente capaz de alimentar el servo |
| Todos los GND | — | GND común, por ejemplo pin físico 6 |

Si el servo usa fuente externa, unir su GND al del Pi y no unir su positivo
al riel del Pi. No alimentar el servo desde un GPIO ni desde 3,3 V.
El LCD fue probado a 3,3 V; su historial incluye fallos intermitentes no
atribuidos a una causa confirmada. No pasar el backpack a 5 V manteniendo I2C
directo: requiere adaptación bidireccional de niveles.

## Instalación en Raspberry Pi 4B

Equipo comprobado: Bookworm, Python 3.11. No requiere pip ni un virtualenv.

```bash
sudo apt install python3-spidev python3-lgpio python3-pigpio pigpio python3-flask sqlite3
sudo systemctl enable --now pigpiod
```

El servicio instalado de pigpiod usa `-l` (socket local). Se conecta por
`localhost` (IPv4 o IPv6, según el daemon). pigpio genera los pulsos de servo en GPIO26; no requiere GPIO18.
SPI debe estar habilitado. El LCD usa `/dev/i2c-3`, dirección `0x27`.
En `/boot/firmware/config.txt`, bajo `[all]`:

```ini
dtparam=spi=on
dtoverlay=i2c-gpio,bus=3,i2c_gpio_sda=23,i2c_gpio_scl=5,i2c_gpio_delay_us=5
```

En `/etc/modules-load.d/rfid-i2c.conf`: `i2c-dev`.
Ya se preparó la persistencia del LCD. Se quitó `spi0-1cs`, que solo era
necesario para el teclado descartado. Los cambios de boot requieren reinicio.
No duplicar overlays si ya existen. `acceso-rfid.service` está instalado,
habilitado y verificado: inicia la aplicación automáticamente con la Pi.

## Padrón RFID

Para añadir una tarjeta sin conocer su UID, en **Alta de RFID** pulsá
**Leer tarjeta con el sensor**, acercá una sola tarjeta al RC522 y esperá que
se complete el campo UID. Retirala, escribí su nombre y pulsá **Agregar**.
La captura vence a los 30 segundos y se puede cancelar. No guarda tarjetas
automáticamente ni abre el servo durante la captura; un ciclo de apertura ya
iniciado conserva su cierre normal. Se exige retirar la tarjeta antes de que
pueda usarse para un nuevo acceso. Solo se admite una captura activa a la vez.

En **Secuencias RFID**, elegí las tarjetas en orden, escribí una única palabra
final de hasta 16 caracteres ASCII y guardá. Podés modificar o eliminar
las secuencias desde la misma página. Una tarjeta solo puede iniciar una
secuencia para evitar ambigüedades. Si se elimina una tarjeta de una secuencia,
la secuencia completa se elimina. Las tarjetas deshabilitadas no se aceptan
para crear pasos nuevos; aparecen marcadas en el selector para que puedas
identificarlas y habilitarlas en el Padrón. Después de guardar un cambio de
tarjeta, el selector se actualiza sin recargar la página. Los cambios del padrón
y las secuencias se guardan en SQLite y sobreviven a un reinicio. Al actualizar
una instalación anterior, la palabra del último paso se conserva como palabra
final de la secuencia.

En **Tiempo de apertura y espera** se puede elegir de 2 a 60 segundos, con
décimas. El mismo valor controla el cierre de la puerta y la espera entre pasos
de una secuencia. Queda guardado en SQLite y se aplica a partir de la siguiente
lectura válida; los plazos que ya comenzaron no cambian.

Los UID iniciales están escritos explícitamente en `padron_rfid.py`:

```python
RFID_INICIALES = (
    ("Llavero 1", "50-C8-E4-A4"),
    ("Llavero 2", "30-83-9E-D3"),
)
```

Se copian una sola vez a `acceso.sqlite3`. Después, la base es la fuente de
verdad: una baja no reaparece al reiniciar. El panel permite alta, edición,
habilitación individual y baja. El selector de modo permite elegir acceso o
combinación sin perder el padrón.

## Ejecutar

```bash
cd /home/pi/rfid-acceso
python3 acceso_rfid.py --validar-config
sudo systemctl enable --now acceso-rfid.service
```

Panel: `http://192.168.3.216:5000/`. La API `/api/estado` se actualiza cada
segundo. La página muestra puerta abierta/cerrada, lector activo, tarjeta
detectada, modo actual y último resultado. El enlace **Ver diagrama** abre
`/diagrama` en otra pestaña para explicar módulos, hilos, procesos y flujos.
El panel está disponible para
la red local sin usuario ni contraseña; no debe exponerse a Internet.

SIGTERM cierra el servo y libera los recursos. No ejecutar drivers de
prueba al mismo tiempo que la aplicación. La aplicación y el registro comparten
un lock para impedir que ambos usen el lector simultáneamente.

`configuracion.json` se busca junto al programa, independientemente del directorio
actual. `tiempo_abierto_s` (5 por defecto) sirve como valor inicial hasta que se
guarda otro desde el panel. También permite cambiar `pulso_cerrado_us`
(1000), `pulso_abierto_us` (1500) y `tiempo_movimiento_s` (0,6). Los pulsos son
posiciones iniciales de prueba para un SG90 posicional; los ángulos exactos se
calibran observando el mecanismo. No se supone que el software mida la posición.

Tras cada movimiento se detienen los pulsos (detach); no se garantiza fuerza de
retención. El plazo usa reloj monotónico; el cierre puede demorarse hasta terminar
una lectura RFID en curso. No hay un sensor que confirme cierre físico.
Un error fatal intenta cerrar antes de salir. Un corte eléctrico o SIGKILL no
permite ejecutar ese cierre: este sistema no ofrece cierre mecánico garantizado.

## Verificación

```bash
python3 -m unittest discover -s tests -v
```

Las pruebas cubren UID/CRC, autorizados y denegados, cierre por tiempo, no extender
el plazo por lecturas repetidas, retirada antes de reabrir y errores de lectura/LCD.
La prueba física debe comprobar ambos llaveros, otro UID no autorizado, retorno
tras 5 s y ausencia de ciclos repetidos mientras un llavero permanece apoyado.

## Fuentes técnicas

- [MFRC522, NXP](https://www.nxp.com/docs/en/data-sheet/MFRC522.pdf).
- [pigpio, fuente oficial](https://github.com/joan2937/pigpio), contrastada con la documentación de `set_servo_pulsewidth` instalada en el Pi.
- API de lgpio y overlays comprobadas en la instalación real del Pi.
