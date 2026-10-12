import os
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QHBoxLayout, QVBoxLayout, QLabel, QComboBox,
    QSizePolicy, QPushButton, QSlider,
    QLineEdit,
    QFileDialog,
    QToolButton,
)
from core.app_paths import base_dir
from ui.gui_templates import create_setting_widget, create_section_header, SettingsBodyWidget
from utils import getTranslationVariant as _
from localization.live import tr_set
from ui.settings.voiceover_settings.presentation import (
    OpenAIEngineSettings,
    OpenVoiceAIHub,
    RestartVoiceService,
    StartTelegramVoice,
    CheckExternalTTS,
)


try:
    import qtawesome as qta
except Exception:
    qta = None


def _external_tts_character_choices(gui):
    """Получить список персонажей без загрузки их игровых данных."""
    names = {}

    try:
        from managers.character_manager import _CHARACTER_DEFINITIONS

        names.update({
            str(item.character_id): str(
                item.character_name or item.character_id
            )
            for item in _CHARACTER_DEFINITIONS
            if str(item.character_id or "").strip()
        })
    except Exception:
        pass

    # Дополняем список данными реестра, если он уже доступен.
    try:
        from core.services import use
        from services.contracts import CharacterRegistry

        for character_id in use(CharacterRegistry).all_ids():
            character_id = str(character_id or "").strip()

            if character_id and character_id not in names:
                names[character_id] = character_id
    except Exception:
        pass

    # В режиме настроек без игрового реестра добавляем выбранного персонажа.
    try:
        selected_id = str(
            gui.settings.get("CHARACTER", "") or ""
        ).strip()

        if selected_id and selected_id not in names:
            names[selected_id] = selected_id
    except Exception:
        pass

    return [
        (f"{display_name} ({character_id})", character_id)
        for character_id, display_name in names.items()
    ]


def _current_external_tts_character_id(gui):
    try:
        from core.services import use
        from services.contracts import CharacterRegistry

        return str(use(CharacterRegistry).current_id() or "").strip()
    except Exception:
        try:
            return str(
                gui.settings.get("CHARACTER", "") or ""
            ).strip()
        except Exception:
            return ""

def build_voiceover_settings_ui(self, parent_layout, *, actions):
    self._voiceover_settings_view_model = actions
    sidebar_w = getattr(self, "SETTINGS_SIDEBAR_WIDTH", 50)
    right_pad = max(8, min(14, int(sidebar_w * 0.22)))

    container = SettingsBodyWidget()
    container_lay = QVBoxLayout(container)
    container_lay.setContentsMargins(0, 0, right_pad, 0)
    container_lay.setSpacing(6)

    create_section_header(container_lay, _("Настройки озвучки", "Voiceover Settings"))

    self.voiceover_section = type('obj', (object,), {'content_frame': parent_layout.parent()})()

    main_config = [
        {'label': _('Использовать озвучку', 'Use speech'),
         'key': 'USE_VOICEOVER', 'type': 'checkbutton',
         'default_checkbutton': False, 'widget_name': 'use_voice_checkbox'},
        {'label': _("Вариант озвучки", "Voiceover Method"),
         'key': 'VOICEOVER_METHOD', 'type': 'combobox',
         'options': ["TG", "Local", "External"], 'default': 'Local',
         'widget_name': 'method_combobox'},
    ]

    for cfg in main_config:
        widget = create_setting_widget(
            gui=self,
            parent=container,
            label=cfg.get('label'),
            setting_key=cfg.get('key', ''),
            widget_type=cfg.get('type', 'entry'),
            options=cfg.get('options'),
            default=cfg.get('default', ''),
            default_checkbutton=cfg.get('default_checkbutton', False),
            widget_name=cfg.get('widget_name')
        )
        if widget:
            container_lay.addWidget(widget)
            if cfg.get('widget_name') == 'method_combobox':
                self.method_frame = widget

    self.tg_settings_frame = SettingsBodyWidget()
    tg_layout = QVBoxLayout(self.tg_settings_frame)
    tg_layout.setContentsMargins(0, 0, 0, 0)
    tg_layout.setSpacing(4)

    tg_config = [
        {'label': _('Автоподключение Telegram', 'Telegram auto-connect'),
         'key': 'TG_AUTOCONNECT', 'type': 'checkbutton',
         'default_checkbutton': False},

        {'label': _('Подключиться к Telegram', 'Connect Telegram'),
         'type': 'button',
         'command': (lambda: actions.dispatch(StartTelegramVoice())),
         'widget_name': 'tg_connect_button'},

        {'label': _('Канал/Сервис', "Channel/Service"), 'key': 'AUDIO_BOT',
         'type': 'combobox', 'options': ["@silero_voice_bot", "@CrazyMitaAIbot"],
         'default': "@silero_voice_bot"},

        {'label': _('Макс. ожидание (сек)', 'Max wait (sec)'), 'key': 'SILERO_TIME',
         'type': 'entry', 'default': '12', 'validation': getattr(self, 'validate_number_0_60', None)},

        {'label': _('Мин. интервал запросов (сек)', 'Min request interval (sec)'),
         'key': 'TG_MIN_REQUEST_INTERVAL',
         'type': 'entry', 'default': '2', 'validation': getattr(self, 'validate_number_0_60', None)},

        {'label': _('Настройки Telegram API', 'Telegram API Settings'), 'type': 'text'},

        {'label': _('Telegram ID', 'Telegram ID'), 'key': 'NM_TELEGRAM_API_ID', 'type': 'entry',
         'default': "", 'hide': bool(self.settings.get("HIDE_PRIVATE"))},
        {'label': _('Telegram Hash', 'Telegram Hash'), 'key': 'NM_TELEGRAM_API_HASH', 'type': 'entry',
         'default': "", 'hide': bool(self.settings.get("HIDE_PRIVATE"))},
        {'label': _('Telegram Phone', 'Telegram Phone'), 'key': 'NM_TELEGRAM_PHONE', 'type': 'entry',
         'default': "", 'hide': bool(self.settings.get("HIDE_PRIVATE"))},
    ]

    for cfg in tg_config:
        widget = create_setting_widget(
            gui=self,
            parent=self.tg_settings_frame,
            label=cfg['label'],
            setting_key=cfg.get('key', ''),
            widget_type=cfg.get('type', 'entry'),
            options=cfg.get('options'),
            default=cfg.get('default', ''),
            validation=cfg.get('validation'),
            hide=cfg.get('hide', False),
            default_checkbutton=cfg.get('default_checkbutton', False),
            command=cfg.get('command'),
            widget_name=cfg.get('widget_name'),
        )
        if widget:
            tg_layout.addWidget(widget)

    container_lay.addWidget(self.tg_settings_frame)

    self.external_settings_frame = SettingsBodyWidget()
    external_layout = QVBoxLayout(self.external_settings_frame)
    external_layout.setContentsMargins(0, 0, 0, 0)
    external_layout.setSpacing(4)
    external_hint = tr_set(
        QLabel(),
        "Укажите URL сервера NeuroMita External TTS API v1 и отдельную папку WAV. Если на диске C мало места, выберите папку на другом диске.",
        "Enter the NeuroMita External TTS API v1 server URL and an audio folder. Choose a different drive if C: is low on space.",
    )
    external_hint.setWordWrap(True)
    external_hint.setObjectName("SeparatorLabel")
    external_layout.addWidget(external_hint)
    external_config = [
        {
            'label': _('URL внешнего TTS-сервера', 'External TTS server URL'),
            'key': 'EXTERNAL_TTS_BASE_URL', 'type': 'entry', 'default': '',
        },
        {
            'label': _('API-ключ', 'API key'),
            'key': 'EXTERNAL_TTS_API_KEY', 'type': 'entry', 'default': '',
            'password': True,
        },
        {
            'label': _('Модель', 'Model'),
            'key': 'EXTERNAL_TTS_MODEL', 'type': 'entry', 'default': 'tts-1',
        },
        {
            'label': _('Профиль голоса (voice ID)', 'Voice profile (voice ID)'),
            'key': 'EXTERNAL_TTS_VOICE_ID', 'type': 'entry', 'default': '',
        },
        {
            'label': _('Папка для внешних WAV', 'External WAV output folder'),
            'key': 'EXTERNAL_TTS_OUTPUT_DIR', 'type': 'entry', 'default': '',
        },
        {
            'label': _('Макс. ожидание синтеза (сек)', 'Synthesis timeout (sec)'),
            'key': 'EXTERNAL_TTS_TIMEOUT', 'type': 'number_stepper',
            'default': 180, 'minimum': 5, 'maximum': 600, 'step': 5,
        },
    ]
    for cfg in external_config:
        widget = create_setting_widget(
            gui=self,
            parent=self.external_settings_frame,
            label=cfg['label'],
            setting_key=cfg['key'],
            widget_type=cfg['type'],
            default=cfg['default'],
            minimum=cfg.get('minimum'),
            maximum=cfg.get('maximum'),
            step=cfg.get('step', 1),
            suffix=cfg.get('suffix', ''),
        )
        if widget:
            if cfg.get('password'):
                editor = widget.findChild(QLineEdit)
                if editor is not None:
                    editor.setEchoMode(QLineEdit.EchoMode.Password)
            elif cfg['key'] == 'EXTERNAL_TTS_OUTPUT_DIR':
                editor = widget.findChild(QLineEdit)
                if editor is not None and widget.layout() is not None:
                    browse = tr_set(QPushButton(), "Обзор…", "Browse…")

                    def choose_output_folder(_checked=False, target=editor):
                        selected = QFileDialog.getExistingDirectory(
                            self,
                            _("Папка для внешних WAV", "External WAV output folder"),
                            target.text() or os.path.expanduser("~"),
                        )
                        if selected:
                            target.setText(selected)
                            self._save_setting("EXTERNAL_TTS_OUTPUT_DIR", selected)

                    browse.clicked.connect(choose_output_folder)
                    widget.layout().addWidget(browse)
            external_layout.addWidget(widget)

    self.external_tts_advanced_button = tr_set(QToolButton(), "Дополнительно", "Advanced")
    self.external_tts_advanced_button.setCheckable(True)
    self.external_tts_advanced_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    self.external_tts_advanced_button.setArrowType(Qt.ArrowType.RightArrow)
    self.external_tts_advanced_frame = SettingsBodyWidget()
    advanced_layout = QVBoxLayout(self.external_tts_advanced_frame)
    advanced_layout.setContentsMargins(12, 0, 0, 0)
    advanced_layout.setSpacing(4)
    self.external_tts_advanced_button.toggled.connect(
        lambda expanded: (
            self.external_tts_advanced_frame.setVisible(expanded),
            self.external_tts_advanced_button.setArrowType(
                Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow
            ),
        )
    )
    external_layout.addWidget(self.external_tts_advanced_button)
    endpoint_settings = (
        ("Путь проверки сервера", "Server health path", "/health", "EXTERNAL_TTS_HEALTH_PATH"),
        ("Путь синтеза", "Synthesis path", "/v1/audio/speech", "EXTERNAL_TTS_SYNTHESIZE_PATH"),
    )
    for label_ru, label_en, default, key in endpoint_settings:
        widget = create_setting_widget(
            gui=self,
            parent=self.external_tts_advanced_frame,
            label=_(label_ru, label_en),
            setting_key=key,
            widget_type="entry",
            default=default,
        )
        if widget:
            advanced_layout.addWidget(widget)
        # Персональные голоса для каждого персонажа.
    from services.external_tts_profiles import (
        EXTERNAL_TTS_CHARACTER_VOICES_SETTING,
        load_external_tts_character_voice_map,
    )

    character_voice_hint = tr_set(
        QLabel(),
        "Задайте отдельный Voice ID для каждой Миты. "
        "Пустое поле использует прежний голос персонажа, "
        "а если он не задан — общий Voice ID.",
        "Assign a separate Voice ID to each character. "
        "An empty field uses the character's legacy voice, "
        "or the global Voice ID if none is configured.",
    )
    character_voice_hint.setWordWrap(True)
    character_voice_hint.setObjectName("SeparatorLabel")
    external_layout.addWidget(character_voice_hint)

    # Строка выбора персонажа.
    character_selector_row = SettingsBodyWidget()
    character_selector_layout = QHBoxLayout(character_selector_row)
    character_selector_layout.setContentsMargins(0, 2, 0, 2)
    character_selector_layout.setSpacing(10)

    character_selector_label = tr_set(
        QLabel(), "Персонаж", "Character"
    )
    character_selector_label.setMinimumWidth(140)
    character_selector_label.setMaximumWidth(140)

    self.external_tts_character_combobox = QComboBox()
    self.external_tts_character_combobox.setObjectName(
        "externalTtsCharacterSelector"
    )
    self.external_tts_character_combobox.setSizePolicy(
        QSizePolicy.Policy.Expanding,
        QSizePolicy.Policy.Fixed,
    )

    for display_name, character_id in _external_tts_character_choices(self):
        self.external_tts_character_combobox.addItem(
            display_name,
            character_id,
        )

    character_selector_layout.addWidget(character_selector_label)
    character_selector_layout.addWidget(
        self.external_tts_character_combobox,
        1,
    )
    external_layout.addWidget(character_selector_row)

    # Поле индивидуального Voice ID.
    character_voice_row = SettingsBodyWidget()
    character_voice_layout = QHBoxLayout(character_voice_row)
    character_voice_layout.setContentsMargins(0, 2, 0, 2)
    character_voice_layout.setSpacing(10)

    character_voice_label = tr_set(
        QLabel(), "Voice ID персонажа", "Character Voice ID"
    )
    character_voice_label.setMinimumWidth(140)
    character_voice_label.setMaximumWidth(140)

    self.external_tts_character_voice_edit = QLineEdit()
    self.external_tts_character_voice_edit.setObjectName(
        "externalTtsCharacterVoiceId"
    )
    self.external_tts_character_voice_edit.setPlaceholderText(
        _(
            "Пустое поле — использовать голос по умолчанию",
            "Empty field — use the default voice",
        )
    )

    save_character_voice_button = tr_set(
        QPushButton(), "Сохранить голос", "Save voice"
    )

    character_voice_layout.addWidget(character_voice_label)
    character_voice_layout.addWidget(
        self.external_tts_character_voice_edit,
        1,
    )
    character_voice_layout.addWidget(save_character_voice_button)
    external_layout.addWidget(character_voice_row)

    self.external_tts_character_voice_status = QLabel()
    self.external_tts_character_voice_status.setWordWrap(True)
    self.external_tts_character_voice_status.setObjectName(
        "SeparatorLabel"
    )
    external_layout.addWidget(self.external_tts_character_voice_status)

    self._external_tts_selected_character_id = ""
    self._external_tts_character_voice_dirty = False
    self._external_tts_character_voice_loading = False

    def _show_character_voice_status(character_id, mapping=None):
        if not isinstance(mapping, dict):
            mapping = load_external_tts_character_voice_map(self.settings)

        voice_id = str(mapping.get(character_id, "") or "").strip()

        if voice_id:
            message = _(
                "Индивидуальный голос сохранён.",
                "Individual voice saved.",
            )
        else:
            message = _(
                "Индивидуальный Voice ID не задан. "
                "Используется прежний голос персонажа или общий голос.",
                "No individual Voice ID set. "
                "The character's legacy voice or global voice will be used.",
            )

        self.external_tts_character_voice_status.setText(message)

    def _save_character_voice(force=False):
        character_id = str(
            self._external_tts_selected_character_id or ""
        ).strip()

        if not character_id:
            return

        if not force and not self._external_tts_character_voice_dirty:
            return

        mapping = load_external_tts_character_voice_map(self.settings)
        voice_id = self.external_tts_character_voice_edit.text().strip()

        if voice_id:
            mapping[character_id] = voice_id
        else:
            # Пустое поле означает отсутствие нового переопределения.
            # Тогда останется доступен legacy external_voice_id.
            mapping.pop(character_id, None)

        self._save_setting(
            EXTERNAL_TTS_CHARACTER_VOICES_SETTING,
            mapping,
        )

        self._external_tts_character_voice_dirty = False
        _show_character_voice_status(character_id, mapping)

    def _load_character_voice(index):
        if self._external_tts_character_voice_loading:
            return

        # Сохраняем изменения предыдущего персонажа перед переключением.
        _save_character_voice(force=False)

        character_id = str(
            self.external_tts_character_combobox.itemData(index) or ""
        ).strip()

        mapping = load_external_tts_character_voice_map(self.settings)

        self._external_tts_selected_character_id = character_id
        self._external_tts_character_voice_loading = True

        self.external_tts_character_voice_edit.setText(
            mapping.get(character_id, "")
        )

        self._external_tts_character_voice_loading = False
        self._external_tts_character_voice_dirty = False

        _show_character_voice_status(character_id, mapping)

    self.external_tts_character_voice_edit.textEdited.connect(
        lambda _text: setattr(
            self,
            "_external_tts_character_voice_dirty",
            True,
        )
    )

    self.external_tts_character_voice_edit.editingFinished.connect(
        lambda: _save_character_voice(force=False)
    )

    save_character_voice_button.clicked.connect(
        lambda _checked=False: _save_character_voice(force=True)
    )

    self.external_tts_character_combobox.currentIndexChanged.connect(
        _load_character_voice
    )

    # При первом открытии показываем текущего персонажа, если он есть в списке.
    selected_character_id = _current_external_tts_character_id(self)

    selected_index = self.external_tts_character_combobox.findData(
        selected_character_id
    )

    if selected_index < 0 and self.external_tts_character_combobox.count():
        selected_index = 0

    self.external_tts_character_combobox.setCurrentIndex(selected_index)

    if selected_index >= 0:
        _load_character_voice(selected_index)
    self.external_tts_guide_button = tr_set(
        QPushButton(), "Как настроить External TTS", "How to set up External TTS"
    )
    external_tts_guide = base_dir() / "docs" / "external_tts_api_v1.md"
    self.external_tts_guide_button.clicked.connect(
        lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(external_tts_guide)))
    )
    advanced_layout.addWidget(self.external_tts_guide_button)
    self.external_tts_advanced_frame.setVisible(False)
    external_layout.addWidget(self.external_tts_advanced_frame)

    check_row = SettingsBodyWidget()
    check_layout = QHBoxLayout(check_row)
    check_layout.setContentsMargins(0, 2, 0, 2)
    self.external_tts_check_button = tr_set(
        QPushButton(),
        "Проверить подключение",
        "Check connection",
    )
    self.external_tts_check_button.clicked.connect(
        lambda: actions.dispatch(CheckExternalTTS())
    )
    self.external_tts_status_label = QLabel()
    self.external_tts_status_label.setWordWrap(True)
    self.external_tts_status_label.setObjectName("SeparatorLabel")
    check_layout.addWidget(self.external_tts_check_button)
    check_layout.addWidget(self.external_tts_status_label, 1)
    external_layout.addWidget(check_row)
    container_lay.addWidget(self.external_settings_frame)

    self.local_settings_frame = SettingsBodyWidget()
    local_layout = QVBoxLayout(self.local_settings_frame)
    local_layout.setContentsMargins(0, 0, 0, 0)
    local_layout.setSpacing(4)

    local_model_row = SettingsBodyWidget()
    local_model_layout = QHBoxLayout(local_model_row)
    local_model_layout.setContentsMargins(0, 2, 0, 2)
    local_model_layout.setSpacing(10)

    label_part = QHBoxLayout()
    label_part.setContentsMargins(0, 0, 0, 0)
    label_part.setSpacing(2)

    local_model_label = tr_set(QLabel(), "Локальная модель", "Local Model")

    label_part.addWidget(local_model_label)

    label_container = SettingsBodyWidget()
    label_container.setLayout(label_part)
    label_container.setMinimumWidth(140)
    label_container.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)

    self.local_voice_combobox = QComboBox()
    self.local_voice_empty_status = QLabel(
        _(
            'Нет установленных моделей. <a href="install">Установить</a>',
            'No installed models. <a href="install">Install</a>',
        )
    )
    self.local_voice_empty_status.setObjectName("SeparatorLabel")
    self.local_voice_empty_status.setTextFormat(Qt.TextFormat.RichText)
    self.local_voice_empty_status.setTextInteractionFlags(
        Qt.TextInteractionFlag.TextBrowserInteraction
    )
    self.local_voice_empty_status.setOpenExternalLinks(False)
    self.local_voice_empty_status.linkActivated.connect(
        lambda _href: actions.dispatch(OpenAIEngineSettings())
    )
    self.local_voice_empty_status.setVisible(False)

    # Шестерёнка справа от модели → настройки конкретной модели (AI Hub, раздел TTS).
    self.local_model_settings_btn = QPushButton()
    self.local_model_settings_btn.setObjectName("VoiceModelSettingsButton")
    self.local_model_settings_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    self.local_model_settings_btn.setFixedSize(30, 30)
    self.local_model_settings_btn.setToolTip(_("Настройки модели", "Model settings"))
    if qta is not None:
        try:
            self.local_model_settings_btn.setIcon(qta.icon("fa5s.cog", color="#cccccc"))
        except Exception:
            self.local_model_settings_btn.setText("")
    else:
        self.local_model_settings_btn.setText("")
    def _open_current_model_settings():
        # Открываем AI Hub на разделе TTS и сразу выделяем текущую модель.
        # component_id в реестре — "tts:<model_id>" (см. make_component_id).
        mid = None
        if self.local_voice_combobox is not None:
            mid = self.local_voice_combobox.currentData()
        if not mid:
            mid = self.settings.get("NM_CURRENT_VOICEOVER")
        mid = str(mid or "").strip()
        actions.dispatch(OpenVoiceAIHub(mid or None))

    self.local_model_settings_btn.clicked.connect(_open_current_model_settings)

    local_model_layout.addWidget(label_container)
    local_model_layout.addWidget(self.local_voice_combobox, 1)
    local_model_layout.addWidget(self.local_voice_empty_status, 1)
    local_model_layout.addWidget(self.local_model_settings_btn, 0)
    local_layout.addWidget(local_model_row)

    # Строка статуса локальной модели: цветной чип-состояние + адаптивная
    # кнопка действия («Установить» / «Инициализировать»). Состояния и подписи
    # выставляет VoiceoverGuiController._sync_local_model_status, действие кнопки
    # разруливает wire_voiceover_settings_logic по свойству "action".
    status_row = SettingsBodyWidget()
    status_layout = QHBoxLayout(status_row)
    status_layout.setContentsMargins(0, 0, 0, 2)
    status_layout.setSpacing(8)

    self.local_model_status_chip = QLabel()
    self.local_model_status_chip.setObjectName("VoiceModelStatusChip")
    self.local_model_status_chip.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

    self.local_model_action_btn = QPushButton()
    self.local_model_action_btn.setObjectName("VoiceModelActionButton")
    self.local_model_action_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    self.local_model_action_btn.setVisible(False)

    status_layout.addWidget(self.local_model_status_chip)
    status_layout.addStretch(1)
    status_layout.addWidget(self.local_model_action_btn)
    local_layout.addWidget(status_row)

    # Громкость воспроизведения в питоне (0..200%). Значения выше 100% усиливают
    # звук покадрово в AudioHandler, чтобы можно было сделать озвучку громче исходной.
    if self.settings.get("VOICEOVER_LOCAL_VOLUME") is None:
        self.settings.set("VOICEOVER_LOCAL_VOLUME", 100)
    try:
        _init_volume = int(self.settings.get("VOICEOVER_LOCAL_VOLUME", 100))
    except (TypeError, ValueError):
        _init_volume = 100
    _init_volume = max(0, min(200, _init_volume))

    volume_row = SettingsBodyWidget()
    volume_layout = QHBoxLayout(volume_row)
    volume_layout.setContentsMargins(0, 2, 0, 2)
    volume_layout.setSpacing(10)

    volume_label = tr_set(QLabel(), "Громкость озвучки", "Voiceover volume")
    volume_label.setMinimumWidth(140)
    volume_label.setMaximumWidth(140)
    volume_label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)

    self.local_volume_slider = QSlider(Qt.Orientation.Horizontal)
    self.local_volume_slider.setMinimum(0)
    self.local_volume_slider.setMaximum(200)
    self.local_volume_slider.setSingleStep(5)
    self.local_volume_slider.setPageStep(10)
    self.local_volume_slider.setValue(_init_volume)

    self.local_volume_value_label = QLabel(f"{_init_volume}%")
    self.local_volume_value_label.setMinimumWidth(44)
    self.local_volume_value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

    def _on_volume_changed(value):
        self.local_volume_value_label.setText(f"{int(value)}%")
        # Во время перетаскивания не спамим сохранением — запишем на отпускании.
        if not self.local_volume_slider.isSliderDown():
            self._save_setting("VOICEOVER_LOCAL_VOLUME", int(value))

    def _on_volume_released():
        self._save_setting("VOICEOVER_LOCAL_VOLUME", int(self.local_volume_slider.value()))

    self.local_volume_slider.valueChanged.connect(_on_volume_changed)
    self.local_volume_slider.sliderReleased.connect(_on_volume_released)

    volume_layout.addWidget(volume_label)
    volume_layout.addWidget(self.local_volume_slider, 1)
    volume_layout.addWidget(self.local_volume_value_label, 0)
    local_layout.addWidget(volume_row)

    local_config = [
        {'label': _("Язык локальной озвучки", "Local Voice Language"),
         'key': "VOICE_LANGUAGE", 'type': 'combobox',
         'options': ["ru", "en"], 'default': "ru",
         'widget_name': 'voice_language_var'},

        {'label': _('Автозагрузка модели', 'Autoload model'),
         'key': 'LOCAL_VOICE_LOAD_LAST', 'type': 'checkbutton',
         'default_checkbutton': False},

        {'label': _('Озвучивать в чате', 'Voiceover in chat'),
         'key': 'VOICEOVER_LOCAL_CHAT', 'type': 'checkbutton',
         'default_checkbutton': True},

        {'label': _('Перезапустить нейро-ядро озвучки', 'Restart Voice AI Engine'),
         'type': 'button',
         'command': (lambda: actions.dispatch(RestartVoiceService()))},

        {'label': _('Перейти к настройкам AI Engine', 'Open AI Engine settings'),
         'type': 'button',
         'command': (lambda: actions.dispatch(OpenAIEngineSettings()))}
    ]
    if os.environ.get("ENABLE_VOICE_DELETE_CHECKBOX", "0") == "1":
        local_config.insert(2, {
            'label': _('Удалять аудио', 'Delete audio'),
            'key': 'LOCAL_VOICE_DELETE_AUDIO', 'type': 'checkbutton',
            'default_checkbutton': True
        })

    for cfg in local_config:
        widget = create_setting_widget(
            gui=self,
            parent=self.local_settings_frame,
            label=cfg.get('label'),
            setting_key=cfg.get('key', ''),
            widget_type=cfg.get('type', 'entry'),
            options=cfg.get('options'),
            default=cfg.get('default', ''),
            default_checkbutton=cfg.get('default_checkbutton', False),
            command=cfg.get('command'),
            widget_name=cfg.get('widget_name')
        )
        if widget:
            local_layout.addWidget(widget)

    container_lay.addWidget(self.local_settings_frame)

    parent_layout.addWidget(container)
