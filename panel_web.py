"""Panel web local para estado y administración del padrón RFID."""
import secrets
import sqlite3
from threading import Thread

from flask import Flask, abort, flash, jsonify, redirect, render_template, request, url_for
from werkzeug.serving import make_server


def crear_aplicacion(padron, estado, tiempo_abierto_s=5):
    aplicacion = Flask(__name__)
    aplicacion.secret_key = secrets.token_hex(32)
    token_csrf = secrets.token_urlsafe(32)

    def resultado_cambio(mensaje, correcto=True, codigo=400):
        if request.headers.get('Accept') == 'application/json':
            return jsonify(aplicado=correcto, mensaje=mensaje), 200 if correcto else codigo
        flash(mensaje, 'ok' if correcto else 'error')
        return redirect(url_for('inicio'))

    def verificar_csrf():
        if not secrets.compare_digest(request.form.get("csrf", ""), token_csrf):
            abort(400, "Token de formulario inválido; recargá la página.")

    @aplicacion.get("/")
    def inicio():
        return render_template(
            "panel.html",
            tarjetas=padron.listar(),
            secuencias=padron.listar_secuencias(),
            ventana_secuencia_s=padron.tiempo_abierto_s(tiempo_abierto_s),
            estado=estado.instantanea(),
            modo=padron.modo_control(),
            csrf=token_csrf,
        )

    @aplicacion.get("/api/estado")
    def api_estado():
        datos = estado.instantanea()
        datos["modo"] = padron.modo_control()
        datos['tiempo_abierto_s'] = padron.tiempo_abierto_s(tiempo_abierto_s)
        return jsonify(datos)

    @aplicacion.get('/diagrama')
    def diagrama():
        return render_template('diagrama.html')

    @aplicacion.get('/api/tarjetas')
    def api_tarjetas():
        return jsonify([{'id': tarjeta['id'], 'nombre': tarjeta['nombre'],
                         'uid': tarjeta['uid'], 'habilitada': bool(tarjeta['habilitada'])}
                        for tarjeta in padron.listar()])

    @aplicacion.post("/modo")
    def cambiar_modo():
        verificar_csrf()
        try:
            modo = request.form.get('modo')
            padron.fijar_modo_control(modo)
            return resultado_cambio('Cambios aplicados: modo ' + ('acceso.' if modo == 'ACCESO' else 'combinación.'))
        except ValueError as error:
            return resultado_cambio('Cambios no aplicados: ' + str(error), False)
        except sqlite3.Error:
            return resultado_cambio('Cambios no aplicados: no se pudo guardar el modo.', False, 503)

    @aplicacion.post('/tiempo')
    def cambiar_tiempo():
        verificar_csrf()
        try:
            segundos = padron.fijar_tiempo_abierto_s(request.form.get('segundos'))
            return resultado_cambio(f'Cambios aplicados: {segundos:g} segundos desde la próxima lectura.')
        except ValueError as error:
            return resultado_cambio('Cambios no aplicados: ' + str(error), False)
        except sqlite3.Error:
            return resultado_cambio('Cambios no aplicados: no se pudo guardar el tiempo.', False, 503)

    @aplicacion.post('/api/captura')
    def iniciar_captura():
        verificar_csrf()
        try:
            return jsonify(estado.iniciar_captura())
        except ValueError as error:
            return jsonify(error=str(error)), 409

    @aplicacion.post('/api/captura/cancelar')
    def cancelar_captura():
        verificar_csrf()
        try:
            return jsonify(estado.cancelar_captura(request.form.get('id', '')))
        except ValueError as error:
            return jsonify(error=str(error)), 409

    @aplicacion.post("/tarjetas")
    def alta():
        verificar_csrf()
        try:
            padron.crear(request.form.get("nombre", ""), request.form.get("uid", ""),
                         request.form.get("habilitada") == "1")
            flash("RFID agregado.", "ok")
        except ValueError as error:
            flash(str(error), "error")
        return redirect(url_for("inicio"))

    @aplicacion.post("/tarjetas/<int:identificador>/editar")
    def editar(identificador):
        verificar_csrf()
        try:
            padron.modificar(identificador, request.form.get("nombre", ""),
                             request.form.get("uid", ""),
                             request.form.get("habilitada") == "1")
            return resultado_cambio('Cambios aplicados: tarjeta actualizada.')
        except ValueError as error:
            return resultado_cambio('Cambios no aplicados: ' + str(error), False)
        except sqlite3.Error:
            return resultado_cambio('Cambios no aplicados: no se pudo guardar la tarjeta.', False, 503)

    @aplicacion.post("/tarjetas/<int:identificador>/eliminar")
    def eliminar(identificador):
        verificar_csrf()
        try:
            padron.eliminar(identificador)
            flash("RFID eliminado.", "ok")
        except ValueError as error:
            flash(str(error), "error")
        return redirect(url_for("inicio"))

    def pasos_formulario():
        return request.form.getlist('tarjeta_id')

    @aplicacion.post('/secuencias')
    def crear_secuencia():
        verificar_csrf()
        try:
            padron.guardar_secuencia(request.form.get('nombre', ''), pasos_formulario(),
                                     request.form.get('palabra_final', ''))
            return resultado_cambio('Secuencia creada y aplicada.')
        except ValueError as error:
            return resultado_cambio('Secuencia no aplicada: ' + str(error), False)
        except sqlite3.Error:
            return resultado_cambio('Secuencia no aplicada: error al guardar.', False, 503)

    @aplicacion.post('/secuencias/<int:identificador>/editar')
    def editar_secuencia(identificador):
        verificar_csrf()
        try:
            padron.guardar_secuencia(request.form.get('nombre', ''), pasos_formulario(),
                                     request.form.get('palabra_final', ''), identificador)
            return resultado_cambio('Cambios aplicados: secuencia actualizada.')
        except ValueError as error:
            return resultado_cambio('Cambios no aplicados: ' + str(error), False)
        except sqlite3.Error:
            return resultado_cambio('Cambios no aplicados: error al guardar.', False, 503)

    @aplicacion.post('/secuencias/<int:identificador>/eliminar')
    def eliminar_secuencia(identificador):
        verificar_csrf()
        try:
            padron.eliminar_secuencia(identificador)
            return resultado_cambio('Secuencia eliminada.')
        except ValueError as error:
            return resultado_cambio(str(error), False)
        except sqlite3.Error:
            return resultado_cambio('No se pudo eliminar la secuencia.', False, 503)

    return aplicacion


class ServidorWeb:
    def __init__(self, aplicacion, host="0.0.0.0", puerto=5000):
        self.servidor = make_server(host, puerto, aplicacion, threaded=True)
        self.hilo = Thread(target=self.servidor.serve_forever, name="servidor-web", daemon=True)

    def iniciar(self):
        self.hilo.start()

    def cerrar(self):
        self.servidor.shutdown()
        self.hilo.join(timeout=5)
