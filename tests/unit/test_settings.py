import pytest
import yaml

from analizador_video.config.settings import (
    build_settings,
    default_document,
    export_settings,
    load_settings,
    migrate_document,
    settings_from_dict,
)
from analizador_video.domain.enums import ProfileName
from analizador_video.domain.errors import ConfigurationError

LEGACY_V1 = """video: {muestreo_seg: 1.0, ancho_miniatura: 320, alto_miniatura: 180, umbral_pixel: 0.06,
  umbral_cambio: 0.03, umbral_estable: 0.012, espera_max_estable_seg: 4.0, separacion_minima_seg: 2.0,
  captura_periodica_seg: 0, ancho_salida: 1280, calidad_jpg: 88}
transcript: {unir_mismo_hablante_seg: 1.5, modelo_whisper: small, idioma: es, bloque_minutos: 15}
ocr: {idiomas: [es, en], confianza_minima: 0.35, cpu: true, guardar_cada: 10}
reporte: {titulo: Analisis funcional de video, confidencialidad: Informacion confidencial. Uso interno.}
"""


def test_profiles_change_only_their_overrides():
    fast, balanced, best = (load_settings(None, p) for p in ProfileName)
    assert (fast.video.muestreo_seg, balanced.video.muestreo_seg, best.video.muestreo_seg) == (2.0, 1.0, 0.5)
    assert best.ocr.preprocesamiento == ("escala_grises", "contraste")
    assert fast.video.calidad_jpg == balanced.video.calidad_jpg


def test_original_v1_config_is_migrated(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(LEGACY_V1, encoding="utf-8")
    settings = load_settings(path)
    assert settings.ocr.dispositivo == "cpu" and settings.reporte.titulo == "Analisis funcional de video"
    assert any("versión 1" in n for n in migrate_document(yaml.safe_load(LEGACY_V1))[1])


@pytest.mark.parametrize(
    "section,key,value,fragment",
    [
        ("ocr", "guardar_cada", 0, "guardar_cada"),  # problema F
        ("ocr", "guardar_cada", 2.5, "entero"),
        ("ocr", "guardar_cada", True, "numérico"),
        ("video", "umbral_cambio", 3, "entre"),
        ("video", "muestreo_seg", -1, "entre"),
        ("ocr", "idiomas", [], "vacío"),
        ("transcript", "modelo_whisper", "gigante", "uno de"),
        ("reporte", "formatos", ["pdf"], "no válidos"),
        ("transcript", "bloque_minutos", 0, "entre"),
    ],
)
def test_invalid_values_are_reported(section, key, value, fragment):
    doc = default_document()
    doc[section][key] = value
    with pytest.raises(ConfigurationError) as info:
        build_settings(doc)
    assert fragment in info.value.message.details


def test_unknown_keys_missing_sections_and_future_version():
    doc = default_document()
    doc["video"]["muestro_seg"] = 1
    del doc["reporte"]
    with pytest.raises(ConfigurationError) as info:
        build_settings(doc)
    assert "muestro_seg" in info.value.message.details and "reporte" in info.value.message.details
    doc = default_document()
    doc["version"] = 99
    with pytest.raises(ConfigurationError):
        build_settings(doc)


def test_roundtrip_export_import(tmp_path):
    settings = load_settings(None, ProfileName.MAX_ACCURACY)
    assert settings_from_dict(settings.to_dict()) == settings
    target = tmp_path / "soporte.yaml"
    export_settings(settings, target)
    assert load_settings(target, ProfileName.MAX_ACCURACY) == settings


def test_missing_or_broken_file(tmp_path):
    with pytest.raises(ConfigurationError):
        load_settings(tmp_path / "no.yaml")
    bad = tmp_path / "bad.yaml"
    bad.write_text("video: [", encoding="utf-8")
    with pytest.raises(ConfigurationError):
        load_settings(bad)
