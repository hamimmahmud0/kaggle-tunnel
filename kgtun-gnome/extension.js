/* extension.js — GNOME 50 Shell Extension for Kaggle Instance Manager
 *
 * Provides a panel indicator that lists tunnelbroker-discovered
 * instances, supports one-click SSH, and shows credentials.
 *
 * ESM module format for GNOME 45+.
 */

import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import GObject from 'gi://GObject';
import St from 'gi://St';
import Clutter from 'gi://Clutter';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

// ── HTTP helper (uses curl subprocess — avoids Soup 2/3 API issues) ──

function fetchJson(url, token) {
    const args = ['curl', '-s', '-H', 'User-Agent: kgtun-gnome/0.1'];
    if (token) {
        args.push('-H', `Authorization: Bearer ${token}`);
    }
    args.push(url);

    const launcher = new Gio.SubprocessLauncher(
        Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE
    );
    const proc = launcher.spawnv(args);
    const [, stdout] = proc.communicate(null);
    const data = stdout ? new TextDecoder().decode(stdout) : '[]';
    return JSON.parse(data);
}

async function fetchPeers(settings) {
    const baseUrl = settings.get_string('tunnelbroker-url');
    const group = settings.get_string('tunnelbroker-group');
    const token = settings.get_string('group-token');
    if (!baseUrl) return [];
    const url = `${baseUrl.replace(/\/+$/, '')}/v1/groups/${group}/peers`;
    const data = await fetchJson(url, token);
    return data.peers || data || [];
}

// ── Panel widget ───────────────────────────────────────────────────────

const KgtunIndicator = GObject.registerClass(
    class KgtunIndicator extends PanelMenu.Button {
        _init(settings) {
            super._init(0.0, 'Kaggle Instance Manager', false);
            this._settings = settings;

            // Panel icon
            this._icon = new St.Icon({
                icon_name: 'computer-symbolic',
                style_class: 'system-status-icon',
            });
            this.add_child(this._icon);

            // Status label
            this._label = new St.Label({
                text: '...',
                y_align: Clutter.ActorAlign.CENTER,
                style_class: 'kgtun-status-label',
            });
            this.add_child(this._label);

            this._timer = null;
            this._peers = [];
        }

        enable() {
            this._refresh();
            const interval = this._settings.get_int('poll-interval-seconds') * 1000;
            this._timer = GLib.timeout_add_seconds(
                GLib.PRIORITY_DEFAULT,
                interval,
                () => { this._refresh(); return GLib.SOURCE_CONTINUE; }
            );
        }

        disable() {
            if (this._timer) {
                GLib.source_remove(this._timer);
                this._timer = null;
            }
            this.menu.removeAll();
        }

        async _refresh() {
            try {
                const peers = await fetchPeers(this._settings);
                this._peers = peers;
                this._rebuildMenu(peers);
                const count = peers.length;
                this._label.set_text(count > 0 ? `${count}` : '');
                this._icon.set_icon_name(
                    count > 0 ? 'network-server-symbolic' : 'computer-symbolic'
                );
            } catch (e) {
                this._label.set_text('!');
                console.error(`[kgtun] fetch error: ${e}`);
            }
        }

        _rebuildMenu(peers) {
            this.menu.removeAll();

            if (peers.length === 0) {
                const item = new PopupMenu.PopupMenuItem('No instances found');
                item.setSensitive(false);
                this.menu.addMenuItem(item);
            } else {
                const header = new PopupMenu.PopupMenuItem(
                    `${peers.length} instance(s) — click to connect`,
                    { reactive: false }
                );
                header.setSensitive(false);
                this.menu.addMenuItem(header);
                this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

                for (const peer of peers) {
                    const name = peer.metadata?.instance_name || peer.peer;
                    const hostname = peer.metadata?.hostname || '';
                    const endpoint = peer.endpoint || (peer.contacts?.[0]?.endpoint) || '';
                    const sshUser = peer.metadata?.ssh_user || 'notebook';
                    const sshPort = peer.metadata?.ssh_port || 2222;

                    const subMenu = new PopupMenu.PopupSubMenuMenuItem(name);

                    const statusItem = new PopupMenu.PopupMenuItem(
                        `Host: ${hostname}  |  Port: ${sshPort}`,
                        { reactive: false }
                    );
                    statusItem.setSensitive(false);
                    subMenu.menu.addMenuItem(statusItem);

                    subMenu.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

                    // SSH connect
                    const sshItem = new PopupMenu.PopupMenuItem('Connect SSH');
                    sshItem.connect('activate', () => {
                        this._launchSsh(endpoint || hostname, sshUser, sshPort);
                    });
                    subMenu.menu.addMenuItem(sshItem);

                    // Copy SSH command
                    const copyItem = new PopupMenu.PopupMenuItem('Copy SSH command');
                    copyItem.connect('activate', () => {
                        const sshCmd = `ssh -o StrictHostKeyChecking=accept-new -p ${sshPort} ${sshUser}@${endpoint || hostname}`;
                        this._copyToClipboard(sshCmd);
                    });
                    subMenu.menu.addMenuItem(copyItem);

                    // Copy tunnel URL
                    if (endpoint) {
                        const epItem = new PopupMenu.PopupMenuItem('Copy tunnel URL');
                        epItem.connect('activate', () => {
                            this._copyToClipboard(endpoint);
                        });
                        subMenu.menu.addMenuItem(epItem);
                    }

                    // Copy notebook cell
                    const cellItem = new PopupMenu.PopupMenuItem('Copy notebook cell');
                    cellItem.connect('activate', () => {
                        this._generateAndCopyCell(peer);
                    });
                    subMenu.menu.addMenuItem(cellItem);
                }
            }

            // Separator + actions
            this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

            const openManagerItem = new PopupMenu.PopupMenuItem('Open Manager App');
            openManagerItem.connect('activate', () => { this._openManagerApp(); });
            this.menu.addMenuItem(openManagerItem);

            const refreshItem = new PopupMenu.PopupMenuItem('Refresh');
            refreshItem.connect('activate', () => { this._refresh(); });
            this.menu.addMenuItem(refreshItem);

            const settingsItem = new PopupMenu.PopupMenuItem('Settings');
            settingsItem.connect('activate', () => { this._openSettings(); });
            this.menu.addMenuItem(settingsItem);
        }

        _launchSsh(host, user, port) {
            const sshCmd = `ssh -o StrictHostKeyChecking=accept-new -p ${port} ${user}@${host}`;
            try {
                GLib.spawn_command_line_async(
                    `gnome-terminal -- bash -c '${sshCmd.replace(/'/g, "'\\''")}; exec bash'`
                );
            } catch (e) {
                console.error(`[kgtun] Failed to launch SSH: ${e}`);
            }
        }

        _copyToClipboard(text) {
            const clipboard = St.Clipboard.get_default();
            clipboard.set_text(St.ClipboardType.CLIPBOARD, text);
        }

        _findKaggleTunnelPath() {
            const envPath = GLib.getenv('KAGGLE_TUNNEL_PYTHONPATH');
            if (envPath) {
                const testPath = GLib.build_filenamev([envPath, 'kaggle_tunnel', 'proxy.py']);
                if (GLib.file_test(testPath, GLib.FileTest.EXISTS)) {
                    return envPath;
                }
            }
            const candidates = [
                '/usr/lib/kaggle-instance-manager/resources',
                '/usr/lib/x86_64-linux-gnu/kaggle-instance-manager/resources',
                '/usr/local/lib/kaggle-instance-manager/resources',
            ];
            for (const candidate of candidates) {
                const testPath = GLib.build_filenamev([candidate, 'kaggle_tunnel', 'proxy.py']);
                if (GLib.file_test(testPath, GLib.FileTest.EXISTS)) {
                    return candidate;
                }
            }
            return null;
        }

        _generateAndCopyCell(peer) {
            const name = peer.metadata?.instance_name || peer.peer;
            const baseUrl = this._settings.get_string('tunnelbroker-url');
            const group = this._settings.get_string('tunnelbroker-group');
            const token = this._settings.get_string('group-token');
            if (!baseUrl) {
                Main.notify('Kaggle Manager', 'Configure tunnelbroker URL in Settings first');
                return;
            }
            try {
                const script = `
from kaggle_tunnel.app import generate_tunnelbroker_cell_code
c = generate_tunnelbroker_cell_code(
    instance_name='${name.replace(/'/g, "\\'")}',
    tunnelbroker_url='${baseUrl.replace(/'/g, "\\'")}',
    tunnelbroker_group='${group.replace(/'/g, "\\'")}',
    tunnelbroker_token='${token.replace(/'/g, "\\'")}',
)
print(c)
                `.trim();

                const flags = Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE;
                const launcher = new Gio.SubprocessLauncher(flags);
                const bundledPath = this._findKaggleTunnelPath();
                if (bundledPath) {
                    const existing = GLib.getenv('PYTHONPATH') || '';
                    const pythonPath = existing
                        ? `${bundledPath}:${existing}`
                        : bundledPath;
                    launcher.setenv('PYTHONPATH', pythonPath, true);
                }

                const proc = launcher.spawnv(['python3', '-c', script]);
                const [, stdout, stderr] = proc.communicate(null);
                const cellCode = stdout ? stdout.toString() : '';
                if (cellCode) {
                    this._copyToClipboard(cellCode);
                    Main.notify('Kaggle Manager', `Cell code for "${name}" copied to clipboard`);
                } else {
                    Main.notify('Kaggle Manager', 'Failed to generate cell code');
                }
            } catch (e) {
                console.error(`[kgtun] generate cell error: ${e}`);
                Main.notify('Kaggle Manager', 'Error generating cell code');
            }
        }

        _openManagerApp() {
            const appPath = this._settings.get_string('manager-app-path');
            if (appPath) {
                try {
                    GLib.spawn_command_line_async(appPath);
                } catch (e) {
                    console.error(`[kgtun] Failed to launch manager app: ${e}`);
                }
            }
        }

        _openSettings() {
            try {
                GLib.spawn_command_line_async(
                    'gnome-extensions prefs kgtun-manager@hamimmahmud0'
                );
            } catch (e) {
                console.error(`[kgtun] Failed to open settings: ${e}`);
            }
        }
    }
);

// ── Extension entry point (ESM class extending Extension) ──────────────

export default class KgtunExtension extends Extension {
    enable() {
        this._indicator = new KgtunIndicator(this.getSettings());
        Main.panel.addToStatusArea('kgtun-indicator', this._indicator, 1, 'right');
        this._indicator.enable();
    }

    disable() {
        if (this._indicator) {
            this._indicator.disable();
            this._indicator.destroy();
            this._indicator = null;
        }
    }
}
