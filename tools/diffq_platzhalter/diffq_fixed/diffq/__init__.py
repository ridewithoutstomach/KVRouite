# -*- coding: utf-8 -*-
#
# This file is part of KVRouite.
#
# Copyright (C) 2026 by Bernd Eller
#
# KVRouite is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# KVRouite is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
# See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with KVRouite. If not, see <https://www.gnu.org/licenses/>.
#
"""Platzhalter fuer das Paket "diffq" (Voice Remover, core/stimme).

audio-separator importiert in seinem Demucs-Code (states.py, pretrained.py,
utils.py) drei Namen aus "diffq" auf Modulebene, benutzt sie aber nur fuer
QUANTISIERTE Demucs-Modelle - solche, deren Gewichte mit DiffQ geschrumpft
wurden. Das Modell, das KVRouite mitliefert (htdemucs), ist nicht
quantisiert; die drei Namen werden nie gerufen.

Warum trotzdem ein eigenes Modul: unter Windows zieht audio-separator
statt des MIT-lizenzierten Originals (facebookresearch/diffq) die Abspaltung
"diffq-fixed" herein, und die steht unter Creative Commons BY-NC 4.0 - nicht
kommerziell, mit der GPL unvereinbar, in KVRouite nicht auslieferbar.
Festgestellt am 10.09.2026 mit pip-licenses in einer Test-venv. Auf Python
3.14 baut das Original ausserdem nicht (kein Wheel, bitpack.pyx fehlt).

Installiert wird dieses Modul ueber requirements.txt als Verteilung
"diffq-fixed" (siehe pyproject.toml daneben), damit pip die Forderung von
audio-separator als erfuellt ansieht.

Dieses Modul stellt die drei Namen bereit und wirft eine klare Meldung, falls
doch einmal ein quantisiertes Modell geladen wird.
"""


class _NichtVerfuegbar:
    def __init__(self, *args, **kwargs):
        raise RuntimeError(
            "Quantised Demucs models are not supported in KVRouite "
            "(the diffq package is not shipped). Use htdemucs.")


class DiffQuantizer(_NichtVerfuegbar):
    pass


class UniformQuantizer(_NichtVerfuegbar):
    pass


def restore_quantized_state(model, state):
    raise RuntimeError(
        "Quantised Demucs models are not supported in KVRouite "
        "(the diffq package is not shipped). Use htdemucs.")
