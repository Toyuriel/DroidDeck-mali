#!/usr/bin/env python3
from pathlib import Path
import sys

root = Path(sys.argv[1] if len(sys.argv) > 1 else "symbiosis").resolve()

mali = root / "patch/symbiosis/mali_tuning.cpp"
text = mali.read_text(encoding="utf-8")

old = '''    } else if (model == 615 || model == 715 || model == 720) {
        traits.generation = MaliGeneration::Valhall5;
    } else if (model >= 300) {'''
new = '''    } else if (model == 615 || model == 715 || model == 720) {
        traits.generation = MaliGeneration::Valhall5;

        // CloversNX POCO X8 Pro profile.
        // The ARM r49 Mali-G720 MC8 driver is kept to one pipeline worker for
        // the first stability build. We can relax this after device testing.
        if (model == 720) {
            traits.fragile_parallel_compile = true;
        }
    } else if (model >= 300) {'''
if old not in text:
    raise SystemExit("Symbiosis Mali generation table changed; refusing unsafe patch")
text = text.replace(old, new, 1)

marker = '''    // A part with very few cores cannot sustain native resolution regardless of
    // its generation. Core count is a better signal here than model number.
'''
insert = '''    // CloversNX v0.4: conservative Mali-G720 MC8 baseline for POCO X8 Pro.
    // ACNH exposed a long-standing unmapped-buffer failure in Skyline/Strato;
    // on Eden we start by lowering queue/texture pressure rather than carrying
    // that old renderer workaround across architectures.
    {
        std::string name = Lower(traits.device_name);
        if (name.find("mali-g720") != std::string::npos) {
            advice.resolution_index = 2;          // 0.75x for first device test
            advice.allow_async_shaders = false;  // deterministic pipeline order
            advice.gpu_astc = true;               // G720 supports ASTC natively
            advice.texture_budget_fraction = 0.45f;
            advice.rationale =
                "CloversNX G720 safe profile: 0.75x, single-threaded pipeline builds, "
                "native ASTC and a 45% texture-cache share for ARM r49 stability.";
        }
    }

'''
if marker not in text:
    raise SystemExit("Symbiosis advice marker changed; refusing unsafe patch")
text = text.replace(marker, insert + marker, 1)
mali.write_text(text, encoding="utf-8")
print("patched Symbiosis Mali-G720 profile")

# Extend the host test so the G720 classification is pinned by CI.
test = root / "tests/t_mali.cpp"
t = test.read_text(encoding="utf-8")
needle = '''        {"Mali-G710",     true, 16, v13, MaliGeneration::ValhallGen3},
'''
if needle not in t:
    raise SystemExit("Mali test table changed")
t = t.replace(
    needle,
    needle + '        {"Mali-G720 MC8", true, 16, v13, MaliGeneration::Valhall5},\n',
    1,
)
test.write_text(t, encoding="utf-8")
print("extended G720 host test")


# CloversNX v0.4 is a stability diagnostic build. Make Stability genuinely
# deterministic on startup, rather than relying on settings left by a prior run.
auto = root / "patch/symbiosis/auto_modes.cpp"
a = auto.read_text(encoding="utf-8")

old = '''    d.tweaks = {
        {"resolution_setup", "3", "Native resolution (Res1X): no scaling maths to get wrong."},
        {"scaling_filter", "1", "Bilinear."},
        {"anti_aliasing", "0", "Extra passes are extra chances to hit a driver bug."},
        {"gpu_accuracy", "1", "High accuracy: fewer glitches, at some cost."},
        {"use_asynchronous_shaders", "false",
         "Synchronous compilation stutters, but avoids async shader bugs on weak drivers."},
        {"use_asynchronous_gpu_emulation", "true", "Still worth keeping."},
        {"use_disk_shader_cache", "true", "Reduces recompilation."},
        {"astc_recompression", "1", "Lower memory pressure means fewer OOM kills."},
        {"use_speed_limit", "true", "Steady pacing."},
        {"speed_limit", "100", "100%."},
        {"use_reactive_flushing", "false", "A frequent source of hangs on mobile drivers."},
        {"max_anisotropy", "1", "Default (1x)."},
    };'''
new = '''    d.tweaks = {
        {"resolution_setup", "2", "CloversNX Mali safe baseline: 0.75x."},
        {"scaling_filter", "1", "Bilinear."},
        {"anti_aliasing", "0", "Extra passes are extra chances to hit a driver bug."},
        {"gpu_accuracy", "1", "High accuracy: fewer glitches, at some cost."},
        {"use_asynchronous_shaders", "false",
         "Synchronous compilation gives deterministic pipeline order on ARM r49."},
        {"use_asynchronous_gpu_emulation", "true", "Keep CPU/GPU threads decoupled."},
        {"use_disk_shader_cache", "true", "Reduces recompilation."},
        {"astc_recompression", "0", "Do not recompress to BC formats unavailable on Mali-G720."},
        {"accelerate_astc", "1", "Use G720 native ASTC support."},
        {"use_extended_memory_layout", "false", "Preserve Android memory headroom."},
        {"use_speed_limit", "true", "Steady pacing."},
        {"speed_limit", "100", "100%."},
        {"use_vsync", "2", "FIFO avoids building a long presentation queue."},
        {"use_reactive_flushing", "false", "Avoid tiler-hostile mid-frame readback."},
        {"max_anisotropy", "1", "Default (1x)."},
    };'''
if old not in a:
    raise SystemExit("Stability mode changed upstream; refusing unsafe patch")
a = a.replace(old, new, 1)

old = '''    // Do NOT re-apply the mode here.
    //
    // Re-applying on every launch was a mistake: a mode owns resolution,
    // accuracy, filtering and more, so any value the user changed by hand was
    // silently overwritten the next time a game started. The visible symptom is
    // exactly "changing the quality setting does nothing to the frame rate" -
    // the setting really did change, and then got reset before the renderer
    // ever read it.
    //
    // A mode is now applied only when the user picks it. That is the moment
    // they asked for a coherent set of values; every moment after that, their
    // own edits win.
    LogInfo(LogArea::Profile,
            std::string{"startup: mode is "} + ToString(mode) +
                "; leaving settings untouched so manual changes survive");'''
new = '''    // CloversNX v0.4 is a reproducible stability build: the selected mode is
    // applied before the renderer reads graphics settings. Custom remains the
    // escape hatch and is handled above.
    const auto applied = Apply(mode, family, origin);
    LogInfo(LogArea::Profile,
            std::string{"CloversNX startup mode "} + ToString(mode) +
                "; applied " + std::to_string(applied) + " setting(s)");'''
if old not in a:
    raise SystemExit("ApplyCurrentOnStartup implementation changed")
a = a.replace(old, new, 1)
auto.write_text(a, encoding="utf-8")
print("patched Stability startup mode")

# Default a fresh install to Stability and fix the range to include the already
# implemented AaaMin enum value.
up = root / "patch/upstream_changes.patch"
u = up.read_text(encoding="utf-8")
old = '        linkage, 1, 0, 6, "symbiosis_auto_mode", Category::RendererAdvanced};'
new = '        linkage, 3, 0, 7, "symbiosis_auto_mode", Category::RendererAdvanced};'
if old not in u:
    raise SystemExit("Symbiosis auto-mode setting patch changed")
u = u.replace(old, new, 1)
up.write_text(u, encoding="utf-8")
print("defaulted fresh installs to Stability")


# --- CloversNX v0.4.1 Spanish UI -----------------------------------------
# Add Spanish resources for the Symbiosis-only screens. Eden already carries
# its own values-es translation; this file only fills/overrides fork strings.
es = root / "patch/android/values/strings-es.xml"
es.write_text(r'''<?xml version="1.0" encoding="utf-8"?>
<resources>
    <string name="fps_tuning_description">Perfiles de rendimiento por dispositivo y controlador</string>
    <string name="profiles_matched_note">Los perfiles mostrados están filtrados para esta GPU y controlador.</string>
    <string name="launch_game_to_detect">Inicia un juego una vez para detectar la GPU y el controlador.</string>
    <string name="what_to_optimise">¿Qué quieres optimizar?</string>
    <string name="show_profiles_all_hardware">Mostrar perfiles para otro hardware</string>
    <string name="needs_custom_driver_short">Necesita un controlador personalizado</string>
    <string name="requires_custom_driver">Requiere un controlador personalizado que este dispositivo no puede instalar</string>
    <string name="profile_applied">Se aplicaron %1$d ajustes</string>
    <string name="profile_applied_nothing">No cambió nada: estos ajustes ya estaban activos</string>

    <string name="diagnostics">Diagnóstico</string>
    <string name="diagnostics_description">Comprueba controlador, memoria y claves en este dispositivo</string>
    <string name="diagnostics_intro">Ejecuta comprobaciones de hardware sin salir de la aplicación.</string>
    <string name="driver_topology">Topología del controlador</string>
    <string name="memory_state">Estado de memoria</string>
    <string name="symbol_borrowing">Préstamo de símbolos</string>
    <string name="no_data_yet">Todavía no hay datos. Inicia un juego para que la capa inspeccione el controlador.</string>
    <string name="thermal_state">Estado térmico</string>

    <string name="performance_mode_desc">Permite una carga sostenida mayor y avisa cuando conviene reducir la temperatura.</string>
    <string name="safe_mode_active">Modo seguro</string>
    <string name="safe_mode_explain">La sesión anterior terminó inesperadamente, por lo que Symbiosis se desactivó para este inicio.</string>
    <string name="safe_mode_reenable">Volver a activar la capa</string>
    <string name="safe_mode_cleared">La capa volverá a ejecutarse la próxima vez que inicies un juego</string>

    <string name="auto_mode">Modo</string>
    <string name="auto_mode_description">Configura de una vez los ajustes principales para un objetivo concreto.</string>
    <string name="mode_quality">Calidad</string>
    <string name="mode_balanced">Equilibrado</string>
    <string name="mode_performance">Rendimiento</string>
    <string name="mode_stability">Estabilidad</string>
    <string name="mode_compatibility">Compatibilidad</string>
    <string name="mode_turbo">Turbo (genera más calor)</string>
    <string name="mode_custom">Personalizado</string>
    <string name="show_advanced_settings">Mostrar todos los ajustes</string>
    <string name="show_advanced_settings_description">Muestra la lista completa, incluidos ajustes avanzados y opciones de depuración.</string>

    <string name="compat_note">Solo es información de compatibilidad. La aplicación no incluye ni descarga juegos comerciales.</string>
    <string name="mode_applied_for">Modo aplicado para %1$s</string>
    <string name="memory_heavy">uso alto de memoria</string>
    <string name="mali_report">Informe de GPU Mali</string>
    <string name="driver_suggestions">Opciones de controlador</string>

    <string name="utilities">Utilidades</string>
    <string name="utilities_description">Diagnóstico, firmware, copias de partidas y análisis de cierres</string>
    <string name="util_firmware">1. Herramientas de firmware</string>
    <string name="util_rom">2. Comprobación de archivos</string>
    <string name="util_rom_desc">Comprueba archivos antes de usarlos y muestra información útil.</string>
    <string name="util_saves">3. Copias de partidas</string>
    <string name="util_saves_desc">Guarda copias de las partidas fuera del almacenamiento interno de la aplicación.</string>
    <string name="util_shared_dir">4. Carpeta de datos compartida</string>
    <string name="util_shared_dir_desc">Usa una carpeta de otra instalación de Eden para evitar duplicar firmware, claves, juegos y partidas.</string>
    <string name="util_crash">5. Análisis de cierres</string>
    <string name="util_crash_desc">Lee el registro y explica por qué probablemente terminó la sesión anterior.</string>
    <string name="why_did_it_crash">¿Por qué se cerró?</string>

    <string name="compat_broken">No funciona</string>
    <string name="compat_intro">Solo introducción</string>
    <string name="compat_perfect">Perfecto</string>
    <string name="compat_playable">Jugable</string>
    <string name="compat_runs">Funciona con problemas</string>
    <string name="compat_unknown">Desconocido</string>

    <string name="launcher_desc_custom">Todos los parámetros son configurables: resolución, color, tramado, rejilla, saturación y contraste.</string>
    <string name="launcher_desc_eden">Aspecto predeterminado de Symbiosis, sin procesamiento adicional.</string>
    <string name="launcher_desc_gba">240x160 con aspecto LCD y rejilla de píxeles visible.</string>
    <string name="launcher_desc_nds">256x192 con paleta de 18 bits y una rejilla LCD ligera.</string>
    <string name="launcher_desc_ps1">320x240 con color de 15 bits y tramado fuerte.</string>
    <string name="launcher_desc_ps2">640x448 con color de 24 bits y tramado ligero.</string>
    <string name="launcher_desc_ps3">Aspecto de la era 720p con degradación mínima.</string>
    <string name="launcher_desc_ps4">Salida nativa, acento azul y sin procesamiento adicional.</string>
    <string name="launcher_desc_ps5">Salida nativa con tarjetas grandes y diseño claro.</string>
    <string name="launcher_desc_steam">Biblioteca azul oscura con carátulas anchas y cuadrícula compacta.</string>
    <string name="launcher_desc_switch">Tema claro con iconos cuadrados y acento rojo.</string>

    <string name="perf_note_almost_free">Coste mínimo.</string>
    <string name="perf_note_depends">Depende completamente de tus ajustes.</string>
    <string name="perf_note_dramatically_faster">Mucho más rápido que nativo.</string>
    <string name="perf_note_faster">Más rápido que nativo.</string>
    <string name="perf_note_free">Sin coste apreciable.</string>
    <string name="perf_note_much_faster">Bastante más rápido que nativo.</string>

    <string name="rep_applets">  applets:</string>
    <string name="rep_backups">  copias:</string>
    <string name="rep_budget">  presupuesto:</string>
    <string name="rep_cores">  núcleos:</string>
    <string name="rep_device">  dispositivo:</string>
    <string name="rep_driver_topology">Topología de controladores de Symbiosis:</string>
    <string name="rep_essential">  esencial:</string>
    <string name="rep_firmware_contents">Contenido del firmware:</string>
    <string name="rep_fonts">  fuentes:</string>
    <string name="rep_generation">  generación:</string>
    <string name="rep_languages">  idiomas:</string>
    <string name="rep_location">  ubicación:</string>
    <string name="rep_mali_tuning">Ajuste de Mali:</string>
    <string name="rep_memory_state">Estado de memoria de Symbiosis:</string>
    <string name="rep_pressure">  presión:</string>
    <string name="rep_save_vault">Copias de partidas:</string>
    <string name="rep_total">  total:</string>
    <string name="rep_used">  usado:</string>

    <string name="confirm_shared_dir">¿Usar esta carpeta?</string>
    <string name="restart_required_desc">La carpeta de datos se lee al iniciar. Cierra completamente la aplicación y vuelve a abrirla.</string>
    <string name="shared_dir_active">Carpeta compartida: %1$s</string>
    <string name="shared_dir_private">Almacenamiento propio: %1$s</string>
    <string name="shared_dir_warning">No ejecutes dos emuladores a la vez usando la misma carpeta; podrían dañarse partidas o cachés.</string>
    <string name="show_mode_overlay">Mostrar modo en pantalla</string>
    <string name="show_mode_overlay_description">Muestra el modo activo y la escala de renderizado durante el juego.</string>

    <string name="floating_button">Menú</string>
    <string name="floating_button_alpha">Transparencia del botón</string>
    <string name="floating_button_corner">Posición del botón</string>
    <string name="pause_on_menu">Pausar al abrir el menú</string>
    <string name="pause_on_menu_description">Detiene la emulación mientras el menú está abierto.</string>
    <string name="settings_guide">Guía de ajustes</string>
    <string name="settings_guide_description">Explica qué hace cada ajuste y cuándo conviene cambiarlo</string>
    <string name="setup_choose_folder_description">Usar una carpeta existente de Eden en vez de crear una segunda copia</string>
    <string name="setup_data_folder_description">Elige dónde guardar firmware, claves, juegos y partidas.</string>
    <string name="show_floating_button">Botón flotante de menú</string>
    <string name="show_floating_button_description">Botón en pantalla que abre el menú del juego.</string>

    <string name="audit_title">Informe de inicio</string>
    <string name="audit_summary_line">%1$d aplicados, %2$d cambiados por el controlador, %3$d ignorados</string>
    <string name="audit_became">solicitado %1$s, obtenido %2$s</string>
    <string name="audit_fix">Corregir</string>
    <string name="audit_fix_n">Corregir %1$d ajuste(s)</string>
    <string name="audit_fixed_n">Se corrigieron %1$d ajuste(s). Reinicia el juego para aplicarlos.</string>
    <string name="audit_copy">Copiar</string>
    <string name="audit_copied">Informe copiado al portapapeles.</string>
    <string name="audit_no_data">Todavía no hay datos</string>
    <string name="audit_no_data_detail">La mayoría de comprobaciones se completan después de iniciar un juego.</string>
    <string name="symbiosis_audit_button">Botón de informe de inicio</string>
    <string name="symbiosis_audit_button_description">Muestra un botón junto al contador de FPS que explica qué ajustes se aplicaron.</string>

    <string name="emulator_data_description_symbiosis">Usa una carpeta existente de Eden o instala aquí las claves y el firmware.</string>
    <string name="shared_dir_adopted">Usando:\n%1$s\n\nFirmware: %2$d archivos\nClaves: %3$s\nPartidas: %4$s</string>

    <string name="game_folders_description">Tus carpetas, con el número de juegos y el espacio utilizado</string>
    <string name="no_game_folders">Todavía no hay carpetas de juegos.</string>
    <string name="folder_unreadable">No se puede leer; comprueba el permiso de almacenamiento</string>
    <string name="folder_empty">No hay juegos en esta carpeta.</string>
    <plurals name="folder_game_count">
        <item quantity="one">%d juego</item>
        <item quantity="other">%d juegos</item>
    </plurals>

    <string name="tools">Herramientas</string>
    <string name="tools_description">Diagnóstico, ajustes de rendimiento y compatibilidad</string>
    <string name="status_keys">Claves</string>
    <string name="status_firmware">Firmware</string>
    <string name="status_driver">Controlador</string>
    <string name="status_games">Juegos</string>
    <string name="status_saves">Partidas</string>
    <string name="status_shaders">Shaders</string>
    <string name="status_data_root">Carpeta de datos</string>
    <string name="status_change_folder">Cambiar carpeta de datos</string>
    <string name="status_folder_changed">Carpeta de datos: %1$s. Reinicia la aplicación.</string>
    <string name="status_folder_failed">No se pudo usar esa carpeta: %1$s</string>
    <string name="folder_in_subfolder">en %1$s</string>
    <string name="status_storage_needed">Se necesita acceso al almacenamiento</string>
    <string name="status_storage_manual">Abre Ajustes → Aplicaciones → Acceso especial → Acceso a todos los archivos</string>
    <string name="folder_launch_failed">No se pudo abrir el archivo del juego</string>
    <string name="folder_launch_unreadable">No se puede leer el archivo; comprueba claves y firmware</string>
    <string name="engine_choice">Motor de emulación</string>
    <string name="engine_choice_description">Eden o Kenji-NX. Un juego que falla en uno puede funcionar en el otro.</string>
    <string name="live_panel">Panel</string>
    <string name="live_panel_description">Estado, carpetas y archivos</string>
</resources>
''', encoding="utf-8")
print("wrote Symbiosis Spanish resources")

# Validate the Spanish overlay here. It will be merged into the default
# resources after Symbiosis is applied, so Eden's official values-es file stays
# untouched and Android falls back to our Spanish text only for new fork strings.
import xml.etree.ElementTree as ET
ET.parse(es)
print("validated Symbiosis Spanish resources")

# Translate hard-coded auto-mode text that is not backed by Android resources.
auto = root / "patch/symbiosis/auto_modes.cpp"
a = auto.read_text(encoding="utf-8")
replacements = {
    '"Quality"': '"Calidad"',
    '"Best image the device can hold. Lower frame rate."': '"Mejor calidad de imagen. Menor rendimiento."',
    '"Balanced"': '"Equilibrado"',
    '"The sensible default. Start here."': '"Configuración equilibrada para empezar."',
    '"Performance"': '"Rendimiento"',
    '"Highest frame rate. Softer image, occasional glitches."': '"Mayor rendimiento con posibles compromisos visuales."',
    '"Stability"': '"Estabilidad"',
    '"Fewest crashes and stutters. Slower, but predictable."': '"Prioriza estabilidad y reduce cierres inesperados."',
    '"Compatibility"': '"Compatibilidad"',
    '"For games that will not boot or render correctly."': '"Para juegos que no inician o muestran errores gráficos."',
    '"Turbo"': '"Turbo"',
    '"Maximum load up to a temperature limit. Gets hot."': '"Máxima carga hasta el límite térmico configurado."',
    '"AAA минимум"': '"AAA mínimo"',
    '"Самые низкие настройки. Памяти может хватить. Если нет — так и будет."': '"Ajustes mínimos para reducir al máximo el uso de memoria."',
    '"0.25x, без фильтров, без расширенной RAM гостя, кэш шейдеров на диск. "': '"0.25x, sin filtros, sin memoria extendida y con caché de shaders en disco. "',
    '"Не обещает, что открытый мир поедет на Mali-G57 / 8 ГБ. Цель — не "': '"El objetivo es reducir picos de memoria y evitar cierres por falta de RAM. "',
    '"убить процесс по OOM и дать шанс загрузиться."': '""',
}
for old_text, new_text in replacements.items():
    a = a.replace(old_text, new_text)
auto.write_text(a, encoding="utf-8")
print("translated native auto-mode labels")

# Translate the visible parts of the embedded launcher. Comments may remain in
# Russian because they are not rendered.
for rel in ["patch/android/assets/library.html", "patch/android/assets/panel_offline.html"]:
    p = root / rel
    s = p.read_text(encoding="utf-8")
    ui = {
        "Ядра": "Motores",
        "Плагины": "Complementos",
        "Обновить интерфейс": "Actualizar interfaz",
        "Утилиты": "Utilidades",
        "Настройки": "Ajustes",
        "основное ядро · наша оболочка": "motor principal · interfaz integrada",
        "их оболочка · ядро или их APK": "motor alternativo",
        "Лаунчер": "Inicio",
        "Список": "Lista",
        "Конвертер": "Convertidor",
        "нет игр": "sin juegos",
        "Найти игру…": "Buscar juego…",
        "Имя": "Nombre",
        "Недавно": "Recientes",
        "Время": "Tiempo",
        "Все": "Todos",
        "Сейв": "Partida",
        "Мод": "Mod",
        "Не играли": "Sin jugar",
        "Ключи · Прошивка · Игры": "Claves · Firmware · Juegos",
        "загрузка…": "cargando…",
        "Сейвы": "Partidas",
        "＋ Папка": "＋ Carpeta",
        "папка не выбрана": "carpeta no seleccionada",
        "пространство Kenji": "espacio Kenji",
        "Скачать ядро": "Descargar motor",
        "Их APK": "APK alternativo",
        "Встроить оболочку": "Integrar interfaz",
        "Игра": "Juego",
        "нет данных": "sin datos",
        "есть сейв": "hay partida",
        "играли, сейва нет": "jugado, sin partida",
        "не начато": "no iniciado",
        "Откройте из APK Eden": "Ábrelo desde la APK de Eden",
        "ничего не найдено": "no se encontró nada",
        "Найти игры": "Buscar juegos",
        "без имени": "sin nombre",
        "Основное ядро": "Motor principal",
        "Скачать ядро": "Descargar motor",
        "Отмена": "Cancelar",
        "Всё равно запустить": "Iniciar de todos modos",
        "Свойства": "Propiedades",
        "Фото": "Capturas",
        "Копировать TitleID": "Copiar TitleID",
        "AAA минимум": "AAA mínimo",
        "Кешировать шейдеры": "Preparar shaders",
        "Закрыть": "Cerrar",
        "Запустить": "Iniciar",
        "Все фото": "Todas las capturas",
        "Скачать": "Descargar",
        "Проверить": "Comprobar",
        "Выбрать": "Seleccionar",
        "Удалить": "Eliminar",
        "Скрыть": "Ocultar",
        "Панель Symbiosis": "Panel Symbiosis",
        "Читаю состояние…": "Leyendo estado…",
        "Мои игры": "Mis juegos",
        "Папка данных": "Carpeta de datos",
        "Нет данных.": "Sin datos.",
        "Папки с играми не добавлены.": "No hay carpetas de juegos.",
        "В этой папке нет файлов игр.": "No hay archivos de juegos en esta carpeta.",
        "встроенная копия панели": "copia integrada del panel",
        "вне приложения": "fuera de la aplicación",
    }
    for old_text, new_text in ui.items():
        s = s.replace(old_text, new_text)
    p.write_text(s, encoding="utf-8")
print("translated embedded launcher UI")
