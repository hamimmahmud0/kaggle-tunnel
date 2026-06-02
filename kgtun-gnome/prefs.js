/* prefs.js — Settings dialog for the Kaggle Instance Manager extension */

const { Gio, GLib, Gtk } = imports.gi;

const ExtensionUtils = imports.misc.extensionUtils;
const Me = ExtensionUtils.getCurrentExtension();

let _settings = null;

function getSettings() {
    if (!_settings) {
        const schemaId = 'org.gnome.shell.extensions.kgtun-manager';
        const schema = Gio.SettingsSchemaSource.new_from_directory(
            Me.dir.get_child('schemas').get_path(),
            Gio.SettingsSchemaSource.get_default(),
            false
        );
        _settings = new Gio.Settings({ settings_schema: schema.lookup(schemaId, null) });
    }
    return _settings;
}

function init() {
    // Nothing to do here
}

function buildPrefsWidget() {
    const settings = getSettings();
    const grid = new Gtk.Grid({
        column_spacing: 12,
        row_spacing: 12,
        margin_top: 24,
        margin_bottom: 24,
        margin_start: 24,
        margin_end: 24,
        visible: true,
    });

    // Row 0: Tunnelbroker URL
    const urlLabel = new Gtk.Label({
        label: 'Tunnelbroker URL',
        halign: Gtk.Align.START,
        visible: true,
    });
    grid.attach(urlLabel, 0, 0, 1, 1);

    const urlEntry = new Gtk.Entry({
        text: settings.get_string('tunnelbroker-url'),
        placeholder_text: 'https://tunnelbroker.example.workers.dev',
        hexpand: true,
        visible: true,
    });
    settings.bind('tunnelbroker-url', urlEntry, 'text', Gio.SettingsBindFlags.DEFAULT);
    grid.attach(urlEntry, 1, 0, 1, 1);

    // Row 1: Group
    const groupLabel = new Gtk.Label({
        label: 'Group',
        halign: Gtk.Align.START,
        visible: true,
    });
    grid.attach(groupLabel, 0, 1, 1, 1);

    const groupEntry = new Gtk.Entry({
        text: settings.get_string('tunnelbroker-group'),
        hexpand: true,
        visible: true,
    });
    settings.bind('tunnelbroker-group', groupEntry, 'text', Gio.SettingsBindFlags.DEFAULT);
    grid.attach(groupEntry, 1, 1, 1, 1);

    // Row 2: Group Token
    const tokenLabel = new Gtk.Label({
        label: 'Group Token (optional)',
        halign: Gtk.Align.START,
        visible: true,
    });
    grid.attach(tokenLabel, 0, 2, 1, 1);

    const tokenEntry = new Gtk.Entry({
        text: settings.get_string('group-token'),
        visibility: false,
        hexpand: true,
        visible: true,
    });
    settings.bind('group-token', tokenEntry, 'text', Gio.SettingsBindFlags.DEFAULT);
    grid.attach(tokenEntry, 1, 2, 1, 1);

    // Row 3: Poll interval
    const pollLabel = new Gtk.Label({
        label: 'Poll interval (seconds)',
        halign: Gtk.Align.START,
        visible: true,
    });
    grid.attach(pollLabel, 0, 3, 1, 1);

    const pollSpin = new Gtk.SpinButton({
        adjustment: new Gtk.Adjustment({
            lower: 5,
            upper: 300,
            step_increment: 5,
        }),
        value: settings.get_int('poll-interval-seconds'),
        visible: true,
    });
    settings.bind('poll-interval-seconds', pollSpin, 'value', Gio.SettingsBindFlags.DEFAULT);
    grid.attach(pollSpin, 1, 3, 1, 1);

    // Row 4: Manager app path
    const pathLabel = new Gtk.Label({
        label: 'Manager app path',
        halign: Gtk.Align.START,
        visible: true,
    });
    grid.attach(pathLabel, 0, 4, 1, 1);

    const pathEntry = new Gtk.Entry({
        text: settings.get_string('manager-app-path'),
        placeholder_text: '/usr/local/bin/kaggle-instance-manager',
        hexpand: true,
        visible: true,
    });
    settings.bind('manager-app-path', pathEntry, 'text', Gio.SettingsBindFlags.DEFAULT);
    grid.attach(pathEntry, 1, 4, 1, 1);

    return grid;
}
