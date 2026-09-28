"""Padrón persistente de RFID y configuración del control de acceso."""
import re
import math
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock


# Padrón inicial escrito en el código. Se copia a SQLite una única vez.
# Después, la web es la fuente de verdad para altas, modificaciones y bajas.
RFID_INICIALES = (
    ("Llavero 1", "50-C8-E4-A4"),
    ("Llavero 2", "30-83-9E-D3"),
)

PATRON_UID = re.compile(r"[0-9A-F]{2}(?:-[0-9A-F]{2}){3,9}")


def normalizar_uid(uid):
    uid = uid.strip().upper().replace(":", "-").replace(" ", "-")
    if not PATRON_UID.fullmatch(uid) or len(uid.split("-")) not in (4, 7, 10):
        raise ValueError("El UID debe tener 4, 7 o 10 bytes hexadecimales, por ejemplo AA-BB-CC-DD.")
    return uid


class PadronRFID:
    def __init__(self, ruta_base):
        self.ruta_base = Path(ruta_base)
        self._modo_lock = Lock()
        self._inicializar()
        with closing(self._conectar()) as conexion:
            self._modo_control = conexion.execute(
                "SELECT valor FROM configuracion WHERE clave='modo_control'"
            ).fetchone()['valor']

    def _conectar(self):
        conexion = sqlite3.connect(self.ruta_base, timeout=5)
        conexion.row_factory = sqlite3.Row
        conexion.execute("PRAGMA foreign_keys = ON")
        conexion.execute("PRAGMA busy_timeout = 5000")
        return conexion

    def _inicializar(self):
        with closing(self._conectar()) as conexion:
            conexion.execute("PRAGMA journal_mode = WAL")
            conexion.execute("PRAGMA synchronous = NORMAL")
            conexion.executescript("""
                CREATE TABLE IF NOT EXISTS tarjetas (
                    id INTEGER PRIMARY KEY,
                    nombre TEXT NOT NULL,
                    uid TEXT NOT NULL UNIQUE,
                    habilitada INTEGER NOT NULL DEFAULT 1 CHECK (habilitada IN (0, 1)),
                    creada_en_utc TEXT NOT NULL,
                    modificada_en_utc TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS configuracion (
                    clave TEXT PRIMARY KEY,
                    valor TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS secuencias (
                    id INTEGER PRIMARY KEY,
                    nombre TEXT NOT NULL,
                    creada_en_utc TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS pasos_secuencia (
                    secuencia_id INTEGER NOT NULL REFERENCES secuencias(id) ON DELETE CASCADE,
                    orden INTEGER NOT NULL,
                    tarjeta_id INTEGER NOT NULL REFERENCES tarjetas(id),
                    palabra TEXT NOT NULL,
                    PRIMARY KEY (secuencia_id, orden)
                );
                CREATE UNIQUE INDEX IF NOT EXISTS una_secuencia_por_tarjeta_inicial
                    ON pasos_secuencia(tarjeta_id) WHERE orden=0;
            """)
            columnas = {fila['name'] for fila in conexion.execute('PRAGMA table_info(secuencias)')}
            if 'palabra_final' not in columnas:
                conexion.execute("ALTER TABLE secuencias ADD COLUMN palabra_final TEXT NOT NULL DEFAULT ''")
                # Los registros anteriores guardaban una palabra por paso.
                # Conservar la del último paso como resultado de la secuencia.
                conexion.execute('''
                    UPDATE secuencias SET palabra_final=COALESCE((
                        SELECT p.palabra FROM pasos_secuencia p
                        WHERE p.secuencia_id=secuencias.id ORDER BY p.orden DESC LIMIT 1
                    ), '')
                ''')
            sembrado = conexion.execute(
                "SELECT valor FROM configuracion WHERE clave='padron_inicial_cargado'"
            ).fetchone()
            if sembrado is None:
                ahora = datetime.now(timezone.utc).isoformat()
                for nombre, uid in RFID_INICIALES:
                    conexion.execute(
                        "INSERT OR IGNORE INTO tarjetas(nombre, uid, habilitada, creada_en_utc, modificada_en_utc) VALUES (?, ?, 1, ?, ?)",
                        (nombre, uid, ahora, ahora),
                    )
                conexion.execute(
                    "INSERT INTO configuracion(clave, valor) VALUES ('padron_inicial_cargado', '1')"
                )
            # Instalaciones anteriores conservan sus tarjetas y secuencias.
            conexion.execute("INSERT OR IGNORE INTO configuracion(clave, valor) VALUES ('modo_control', 'ACCESO')")
            conexion.execute("DELETE FROM configuracion WHERE clave='control_habilitado'")
            conexion.commit()

    def listar(self):
        with closing(self._conectar()) as conexion:
            return [dict(fila) for fila in conexion.execute(
                "SELECT id, nombre, uid, habilitada, creada_en_utc, modificada_en_utc FROM tarjetas ORDER BY nombre COLLATE NOCASE, id"
            )]

    def obtener(self, identificador):
        with closing(self._conectar()) as conexion:
            fila = conexion.execute(
                "SELECT id, nombre, uid, habilitada FROM tarjetas WHERE id=?", (identificador,)
            ).fetchone()
            return dict(fila) if fila else None

    def esta_autorizado(self, uid):
        with closing(self._conectar()) as conexion:
            return conexion.execute(
                "SELECT 1 FROM tarjetas WHERE uid=? AND habilitada=1", (uid,)
            ).fetchone() is not None

    def existe_uid(self, uid):
        with closing(self._conectar()) as conexion:
            return conexion.execute('SELECT 1 FROM tarjetas WHERE uid=?', (uid,)).fetchone() is not None

    def crear(self, nombre, uid, habilitada=True):
        nombre = nombre.strip()
        if not nombre or len(nombre) > 80:
            raise ValueError("El nombre es obligatorio y admite hasta 80 caracteres.")
        uid = normalizar_uid(uid)
        ahora = datetime.now(timezone.utc).isoformat()
        try:
            with closing(self._conectar()) as conexion:
                conexion.execute(
                    "INSERT INTO tarjetas(nombre, uid, habilitada, creada_en_utc, modificada_en_utc) VALUES (?, ?, ?, ?, ?)",
                    (nombre, uid, int(bool(habilitada)), ahora, ahora),
                )
                conexion.commit()
        except sqlite3.IntegrityError as error:
            raise ValueError("Ese UID ya está registrado.") from error

    def modificar(self, identificador, nombre, uid, habilitada):
        nombre = nombre.strip()
        if not nombre or len(nombre) > 80:
            raise ValueError("El nombre es obligatorio y admite hasta 80 caracteres.")
        uid = normalizar_uid(uid)
        ahora = datetime.now(timezone.utc).isoformat()
        try:
            with closing(self._conectar()) as conexion:
                cursor = conexion.execute(
                    "UPDATE tarjetas SET nombre=?, uid=?, habilitada=?, modificada_en_utc=? WHERE id=?",
                    (nombre, uid, int(bool(habilitada)), ahora, identificador),
                )
                if cursor.rowcount != 1:
                    raise ValueError("La tarjeta ya no existe.")
                conexion.commit()
        except sqlite3.IntegrityError as error:
            raise ValueError("Ese UID ya está registrado.") from error

    def eliminar(self, identificador):
        with closing(self._conectar()) as conexion:
            # Una secuencia incompleta nunca debe quedar operativa.
            conexion.execute("DELETE FROM secuencias WHERE id IN (SELECT secuencia_id FROM pasos_secuencia WHERE tarjeta_id=?)", (identificador,))
            cursor = conexion.execute("DELETE FROM tarjetas WHERE id=?", (identificador,))
            conexion.commit()
            if cursor.rowcount != 1:
                raise ValueError("La tarjeta ya no existe.")

    def listar_secuencias(self):
        with closing(self._conectar()) as conexion:
            secuencias = [dict(f) for f in conexion.execute(
                "SELECT id, nombre, palabra_final FROM secuencias ORDER BY nombre COLLATE NOCASE, id")]
            for secuencia in secuencias:
                secuencia['pasos'] = [dict(f) for f in conexion.execute("""
                    SELECT p.orden, p.tarjeta_id, p.palabra, t.nombre AS tarjeta_nombre, t.uid,
                           t.habilitada
                    FROM pasos_secuencia p JOIN tarjetas t ON t.id=p.tarjeta_id
                    WHERE p.secuencia_id=? ORDER BY p.orden
                """, (secuencia['id'],))]
            return secuencias

    def secuencia_iniciada_por(self, uid):
        for secuencia in self.listar_secuencias():
            if secuencia['pasos'] and secuencia['pasos'][0]['uid'] == uid:
                return secuencia
        return None

    def guardar_secuencia(self, nombre, tarjetas, palabra_final, identificador=None):
        nombre = nombre.strip()
        if not nombre or len(nombre) > 80:
            raise ValueError('El nombre de la secuencia admite entre 1 y 80 caracteres.')
        if not 2 <= len(tarjetas) <= 8:
            raise ValueError('La secuencia debe tener entre 2 y 8 tarjetas.')
        palabra_final = palabra_final.strip()
        if not palabra_final or len(palabra_final) > 16 or any(ord(c) < 32 or ord(c) > 126 for c in palabra_final):
            raise ValueError('La palabra final debe tener entre 1 y 16 caracteres ASCII imprimibles para el LCD.')
        normalizados = []
        for tarjeta_id in tarjetas:
            try:
                tarjeta_id = int(tarjeta_id)
            except (ValueError, TypeError) as error:
                raise ValueError('Seleccioná una tarjeta registrada para cada paso.') from error
            normalizados.append(tarjeta_id)
        with closing(self._conectar()) as conexion:
            with conexion:
                for tarjeta_id in normalizados:
                    fila = conexion.execute('SELECT habilitada FROM tarjetas WHERE id=?', (tarjeta_id,)).fetchone()
                    if fila is None or not fila['habilitada']:
                        raise ValueError('Todos los pasos deben usar tarjetas registradas y habilitadas.')
                inicio = normalizados[0]
                conflicto = conexion.execute('''
                    SELECT 1 FROM pasos_secuencia WHERE orden=0 AND tarjeta_id=? AND secuencia_id!=?
                ''', (inicio, identificador or -1)).fetchone()
                if conflicto:
                    raise ValueError('Esa tarjeta ya inicia otra secuencia.')
                if identificador is None:
                    cursor = conexion.execute(
                        'INSERT INTO secuencias(nombre, palabra_final, creada_en_utc) VALUES (?, ?, ?)',
                        (nombre, palabra_final, datetime.now(timezone.utc).isoformat()))
                    identificador = cursor.lastrowid
                else:
                    cursor = conexion.execute('UPDATE secuencias SET nombre=?, palabra_final=? WHERE id=?',
                                              (nombre, palabra_final, identificador))
                    if cursor.rowcount != 1:
                        raise ValueError('La secuencia ya no existe.')
                    conexion.execute('DELETE FROM pasos_secuencia WHERE secuencia_id=?', (identificador,))
                conexion.executemany('''
                    INSERT INTO pasos_secuencia(secuencia_id, orden, tarjeta_id, palabra)
                    VALUES (?, ?, ?, ?)
                ''', ((identificador, orden, tarjeta_id, '')
                      for orden, tarjeta_id in enumerate(normalizados)))
        return identificador

    def eliminar_secuencia(self, identificador):
        with closing(self._conectar()) as conexion:
            cursor = conexion.execute('DELETE FROM secuencias WHERE id=?', (identificador,))
            conexion.commit()
            if cursor.rowcount != 1:
                raise ValueError('La secuencia ya no existe.')

    def modo_control(self):
        with self._modo_lock:
            return self._modo_control

    def fijar_modo_control(self, modo):
        if modo not in ('ACCESO', 'COMBINACION'):
            raise ValueError('Seleccioná modo acceso o modo combinación.')
        with self._modo_lock:
            with closing(self._conectar()) as conexion:
                conexion.execute(
                    "INSERT INTO configuracion(clave, valor) VALUES ('modo_control', ?) "
                    "ON CONFLICT(clave) DO UPDATE SET valor=excluded.valor",
                    (modo,),
                )
                conexion.commit()
            self._modo_control = modo

    def tiempo_abierto_s(self, predeterminado=5):
        with closing(self._conectar()) as conexion:
            fila = conexion.execute("SELECT valor FROM configuracion WHERE clave='tiempo_abierto_s'").fetchone()
            return float(fila['valor']) if fila else float(predeterminado)

    def fijar_tiempo_abierto_s(self, valor):
        try:
            segundos = float(valor)
        except (ValueError, TypeError) as error:
            raise ValueError('Ingresá un tiempo entre 2 y 60 segundos.') from error
        if not math.isfinite(segundos) or not 2 <= segundos <= 60:
            raise ValueError('Ingresá un tiempo entre 2 y 60 segundos.')
        with closing(self._conectar()) as conexion:
            conexion.execute('''
                INSERT INTO configuracion(clave, valor) VALUES ('tiempo_abierto_s', ?)
                ON CONFLICT(clave) DO UPDATE SET valor=excluded.valor
            ''', (f'{segundos:g}',))
            conexion.commit()
        return segundos
