/* prefs.js — Settings dialog for the Kaggle Instance Manager extension
 *
 * GNOME 45+ (ES module) API — uses Adw.PreferencesGroup inside
 * fillPreferencesWindow().
 */

import Adw from 'gi://Adw';
import Gio from 'gi://Gio';
import Gtk from 'gi://Gtk';
import { ExtensionPreferences } from 'resource:///org/gnome/Shell/Extensions/js/extensions/prefs.js';

export default class KgtunPreferences extends ExtensionPreferences {
    fillPreferencesWindow(window) {
        const settings = this.getSettings();

        // ── Tunnelbroker group ───────────────────────────────────────
        const tbGroup = new Adw.PreferencesGroup({
            title: 'Tunnelbroker',
            description: 'Configure the tunnelbroker peer discovery service',
        });

        // Row: Tunnelbroker URL
        const urlRow = new Adw.ActionRow({
            title: 'Tunnelbroker URL',
            subtitle: 'Base URL of the tunnelbroker Worker',
        });
        const urlEntry = new Gtk.Entry({
            text: settings.get_string('tunnelbroker-url'),
            placeholder_text: 'https://tunnelbroker.example.workers.dev',
            hexpand: true,
        });
        urlRow.add_suffix(urlEntry);
        urlRow.set_activatable_widget(urlEntry);
        settings.bind('tunnelbroker-url', urlEntry, 'text', Gio.SettingsBindFlags.DEFAULT);
        tbGroup.add(urlRow);

        // Row: Group
        const groupRow = new Adw.ActionRow({
            title: 'Group',
            subtitle: 'Peer group namespace',
        });
        const groupEntry = new Gtk.Entry({
            text: settings.get_string('tunnelbroker-group'),
            hexpand: true,
        });
        groupRow.add_suffix(groupEntry);
        groupRow.set_activatable_widget(groupEntry);
        settings.bind('tunnelbroker-group', groupEntry, 'text', Gio.SettingsBindFlags.DEFAULT);
        tbGroup.add(groupRow);

        // Row: Group Token
        const tokenRow = new Adw.ActionRow({
            title: 'Group Token',
            subtitle: 'Bearer token for authenticated groups (optional)',
        });
        const tokenEntry = new Gtk.Entry({
            text: settings.get_string('group-token'),
            visibility: false,
            hexpand: true,
        });
        tokenRow.add_suffix(tokenEntry);
        tokenRow.set_activatable_widget(tokenEntry);
        settings.bind('group-token', tokenEntry, 'text', Gio.SettingsBindFlags.DEFAULT);
        tbGroup.add(tokenRow);

        // ── Display group ────────────────────────────────────────────
        const displayGroup = new Adw.PreferencesGroup({
            title: 'Display',
            description: 'Update frequency and application paths',
        });

        // Row: Poll interval
        const pollRow = new Adw.ActionRow({
            title: 'Poll Interval',
            subtitle: 'How often to refresh the instance list (seconds)',
        });
        const pollSpin = new Gtk.SpinButton({
            adjustment: new Gtk.Adjustment({
                lower: 5,
                upper: 300,
                step_increment: 5,
            }),
            value: settings.get_int('poll-interval-seconds'),
            hexpand: true,
        });
        pollRow.add_suffix(pollSpin);
        pollRow.set_activatable_widget(pollSpin);
        settings.bind('poll-interval-seconds', pollSpin, 'value', Gio.SettingsBindFlags.DEFAULT);
        displayGroup.add(pollRow);

        // Row: Manager app path
        const pathRow = new Adw.ActionRow({
            title: 'Manager App Path',
            subtitle: 'Path to the Kaggle Instance Manager desktop app',
        });
        const pathEntry = new Gtk.Entry({
            text: settings.get_string('manager-app-path'),
            placeholder_text: '/usr/local/bin/kaggle-instance-manager',
            hexpand: true,
        });
        pathRow.add_suffix(pathEntry);
        pathRow.set_activatable_widget(pathEntry);
        settings.bind('manager-app-path', pathEntry, 'text', Gio.SettingsBindFlags.DEFAULT);
        displayGroup.add(pathRow);

        // ── Add page to the window ────────────────────────────────────
        const page = new Adw.PreferencesPage();
        page.add(tbGroup);
        page.add(displayGroup);
        window.add(page);
    }
}
