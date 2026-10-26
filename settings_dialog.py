"""Настройки Капри: горячая клавиша, периодические факты и фильтрация микрофона."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QSpinBox, QCheckBox, QPushButton, QSlider, QMessageBox)

class SettingsDialog(QDialog):
    def __init__(self, capri, parent=None):
        super().__init__(parent)
        self.capri = capri
        self.setWindowTitle('Настройки Капри')
        self.setMinimumWidth(420)
        root = QVBoxLayout(self)
        intro = QLabel('Настрой поведение Капри. Изменения сохраняются в config.json.')
        intro.setWordWrap(True); root.addWidget(intro)
        form = QFormLayout(); root.addLayout(form)
        self.hotkey = QLineEdit(str(capri.cfg.get('text_hotkey', 'ctrl+shift+space')))
        self.hotkey.setPlaceholderText('например ctrl+shift+space')
        form.addRow('Горячая клавиша для письменного запроса:', self.hotkey)
        self.fact_enabled = QCheckBox('Появляться и рассказывать факт по последнему запросу')
        self.fact_enabled.setChecked(bool(capri.cfg.get('fact_enabled', True)))
        form.addRow('Интересные факты:', self.fact_enabled)
        self.fact_minutes = QSpinBox(); self.fact_minutes.setRange(1, 240)
        self.fact_minutes.setValue(int(capri.cfg.get('fact_interval_minutes', 10)))
        self.fact_minutes.setSuffix(' мин')
        form.addRow('Интервал:', self.fact_minutes)
        self.fact_minutes.setEnabled(self.fact_enabled.isChecked())
        self.fact_enabled.toggled.connect(self.fact_minutes.setEnabled)
        self.sensitivity = QSlider(Qt.Orientation.Horizontal); self.sensitivity.setRange(10, 200)
        self.sensitivity.setValue(int(capri.cfg.get('mic_sensitivity', 100)))
        self.sensitivity_value = QLabel(f'{self.sensitivity.value()}%')
        self.sensitivity.valueChanged.connect(lambda v: self.sensitivity_value.setText(f'{v}%'))
        sensrow = QHBoxLayout(); sensrow.addWidget(self.sensitivity, 1); sensrow.addWidget(self.sensitivity_value)
        form.addRow('Фильтрация помех микрофона:', sensrow)
        self.web_search = QCheckBox('Искать информацию в интернете для вопросов о свежих событиях')
        self.web_search.setChecked(bool(capri.cfg.get('search_when_unsure', True)))
        form.addRow('Интернет-поиск:', self.web_search)
        note = QLabel('Если горячая клавиша не срабатывает, установи зависимость: python -m pip install keyboard. '
                      'Повышенная чувствительность лучше слышит тихую речь, но может ловить шум.')
        note.setWordWrap(True); note.setStyleSheet('color: gray;'); root.addWidget(note)
        buttons = QHBoxLayout(); buttons.addStretch(1)
        save = QPushButton('Сохранить'); cancel = QPushButton('Отмена')
        save.clicked.connect(self.save); cancel.clicked.connect(self.reject)
        buttons.addWidget(save); buttons.addWidget(cancel); root.addLayout(buttons)

    def save(self):
        hotkey = self.hotkey.text().strip().lower()
        if not hotkey:
            QMessageBox.warning(self, 'Настройки', 'Укажи сочетание клавиш.'); return
        self.capri.cfg['text_hotkey'] = hotkey
        self.capri.cfg['fact_enabled'] = self.fact_enabled.isChecked()
        self.capri.cfg['fact_interval_minutes'] = self.fact_minutes.value()
        self.capri.cfg['mic_sensitivity'] = self.sensitivity.value()
        self.capri.cfg['search_when_unsure'] = self.web_search.isChecked()
        import json, os
        config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            for k in ('text_hotkey','fact_enabled','fact_interval_minutes','mic_sensitivity','search_when_unsure'):
                data[k] = self.capri.cfg[k]
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.write('\n')
        except Exception as exc:
            QMessageBox.critical(self, 'Настройки', f'Не удалось сохранить config.json: {exc}')
            return
        if self.capri.listener:
            self.capri.listener.sensitivity = self.capri.cfg['mic_sensitivity']
        self.capri.register_text_hotkey()
        self.capri.reset_fact_timer()
        self.accept()
