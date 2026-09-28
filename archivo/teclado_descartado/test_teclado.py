import unittest
from unittest.mock import Mock, patch
from teclado_matricial import DebounceTeclado, TecladoMatricial, GPIO_FILAS, GPIO_COLUMNAS


class PruebasTeclado(unittest.TestCase):
    def test_rebote_y_pulsacion_sostenida(self):
        filtro = DebounceTeclado()
        muestras = [set(), {'1'}, set(), {'1'}, {'1'}, {'1'}, {'1'}]
        eventos = [filtro.actualizar(muestra, i * 0.03) for i, muestra in enumerate(muestras)]
        self.assertEqual([e for e in eventos if e], ['1'])

    def test_no_acepta_muestras_demasiado_proximas(self):
        filtro = DebounceTeclado()
        self.assertIsNone(filtro.actualizar({'2'}, 0))
        self.assertIsNone(filtro.actualizar({'2'}, 0.005))
        self.assertEqual(filtro.actualizar({'2'}, 0.025), '2')

    def test_multitecla_exige_liberacion_estable(self):
        filtro = DebounceTeclado()
        muestras = [{'1', '2'}, {'1'}, {'1'}, set(), set(), {'3'}, {'3'}]
        eventos = [filtro.actualizar(muestra, i * 0.03) for i, muestra in enumerate(muestras)]
        self.assertEqual([e for e in eventos if e], ['3'])

    def test_puede_repetir_tras_soltar(self):
        filtro = DebounceTeclado()
        muestras = [{'#'}, {'#'}, set(), set(), {'#'}, {'#'}]
        eventos = [filtro.actualizar(muestra, i * 0.03) for i, muestra in enumerate(muestras)]
        self.assertEqual([e for e in eventos if e], ['#', '#'])

    def test_filas_inactivas_input_y_activa_siempre_low(self):
        teclado = TecladoMatricial.__new__(TecladoMatricial)
        teclado.gestor = 1
        teclado.gpio = Mock()
        teclado.gpio.SET_PULL_NONE = 0
        estados = {pin: 'input' for pin in GPIO_FILAS}
        def salida(handle, pin, valor, flags):
            self.assertEqual(valor, 0)
            self.assertTrue(all(estado == 'input' for estado in estados.values()))
            estados[pin] = 'low'
        def entrada(handle, pin, flags):
            estados[pin] = 'input'
        def leer(handle, columna):
            self.assertEqual(list(estados.values()).count('low'), 1)
            return 0 if estados[GPIO_FILAS[1]] == 'low' and columna == GPIO_COLUMNAS[2] else 1
        teclado.gpio.gpio_claim_output.side_effect = salida
        teclado.gpio.gpio_claim_input.side_effect = entrada
        teclado.gpio.gpio_read.side_effect = leer
        with patch('teclado_matricial.time.sleep'):
            self.assertEqual(teclado.muestrear(), frozenset({'6'}))
        self.assertTrue(all(estado == 'input' for estado in estados.values()))


if __name__ == '__main__':
    unittest.main()
