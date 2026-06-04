/* extension.js — GNOME 50 Shell Extension for Kaggle Instance Manager
 *
 * Provides a panel indicator that lists tunnelbroker-discovered
 * instances, supports one-click SSH, and shows credentials.
 */

const { Gio, GLib, GObject, Soup } = imports.gi;
const Main = imports.ui.main;
const PanelMenu = imports.ui.panelMenu;
const PopupMenu = imports.ui.popupMenu;
const St = imports.gi.St;

const ExtensionUtils = imports.misc.extensionUtils;
const Me = ExtensionUtils.getCurrentExtension();

// ── GSettings ──────────────────────────────────────────────────────────

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

// ── HTTP helper ────────────────────────────────────────────────────────

async function fetchJson(url) {
    const session = new Soup.Session({ user_agent: 'kgtun-gnome/0.1' });
    const msg = Soup.Message.new('GET', url);

    // Add auth header if configured
    const token = getSettings().get_string('group-token');
    if (token) {
        msg.request_headers.append('Authorization', `Bearer ${token}`);
    }

    return new Promise((resolve, reject) => {
        session.send_async(msg, null, (source, result) => {
            try {
                const bytes = source.send_finish(result);
                const decoder = new TextDecoder();
                const body = decoder.decode(bytes.get_data());
                resolve(JSON.parse(body));
            } catch (e) {
                reject(e);
            }
        });
    });
}

async function fetchPeers() {
    const baseUrl = getSettings().get_string('tunnelbroker-url');
    const group = getSettings().get_string('tunnelbroker-group');
    if (!baseUrl) return [];

    const url = `${baseUrl.replace(/\/+$/, '')}/v1/groups/${group}/peers`;
    const data = await fetchJson(url);
    return data.peers || data || [];
}

// ── Panel widget ───────────────────────────────────────────────────────

const KgtunIndicator = GObject.registerClass(
    class KgtunIndicator extends PanelMenu.Button {
        _init() {
            super._init(0.0, 'Kaggle Instance Manager', false);

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

            // Timer
            this._timer = null;
            this._peers = [];
        }

        enable() {
            this._refresh();
            const interval = getSettings().get_int('poll-interval-seconds') * 1000;
            this._timer = GLib.timeout_add_seconds(
                GLib.Priority.DEFAULT,
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
                const peers = await fetchPeers();
                this._peers = peers;
                this._rebuildMenu(peers);

                // Update label
                const count = peers.length;
                this._label.set_text(count > 0 ? `${count}` : '');
                this._icon.set_icon_name(
                    count > 0 ? 'network-server-symbolic' : 'computer-symbolic'
                );
            } catch (e) {
                this._label.set_text('!');
                log(`[kgtun] fetch error: ${e}`);
            }
        }

        _rebuildMenu(peers) {
            this.menu.removeAll();

            if (peers.length === 0) {
                const item = new PopupMenu.PopupMenuItem('No instances found');
                item.setSensitive(false);
                this.menu.addMenuItem(item);
            } else {
                // Header
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

                    // Instance sub-menu
                    const subMenu = new PopupMenu.PopupSubMenuMenuItem(name);

                    // Status row
                    const statusItem = new PopupMenu.PopupMenuItem(
                        `Host: ${hostname}  |  Port: ${sshPort}`,
                        { reactive: false }
                    );
                    statusItem.setSensitive(false);
                    subMenu.menu.addMenuItem(statusItem);

                    // SSH connect
                    subMenu.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
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

                    // Copy endpoint
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

                    this.menu.addMenuItem(subMenu);
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
                log(`[kgtun] Failed to launch SSH: ${e}`);
            }
        }

        _copyToClipboard(text) {
            const clipboard = St.Clipboard.get_default();
            clipboard.set_text(St.ClipboardType.CLIPBOARD, text);
        }

        // Try to find the bundled kaggle_tunnel Python package so we can
        // set PYTHONPATH when running the cell generator subprocess.
        // Checks KAGGLE_TUNNEL_PYTHONPATH env var first, then known paths.
        _findKaggleTunnelPath() {
            // 1. Environment variable (used by Snap / manual configs)
            const envPath = GLib.getenv('KAGGLE_TUNNEL_PYTHONPATH');
            if (envPath) {
                const testPath = GLib.build_filenamev([envPath, 'kaggle_tunnel', 'proxy.py']);
                if (GLib.file_test(testPath, GLib.FileTest.EXISTS)) {
                    return envPath;
                }
            }

            // 2. Common .deb installation paths
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
            const baseUrl = getSettings().get_string('tunnelbroker-url');
            const group = getSettings().get_string('tunnelbroker-group');
            const token = getSettings().get_string('group-token');
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

                // Set PYTHONPATH so the bundled kaggle_tunnel package is found
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
                log(`[kgtun] generate cell error: ${e}`);
                Main.notify('Kaggle Manager', 'Error generating cell code');
            }
        }

        _openManagerApp() {
            const appPath = getSettings().get_string('manager-app-path');
            if (appPath) {
                try {
                    GLib.spawn_command_line_async(appPath);
                } catch (e) {
                    log(`[kgtun] Failed to launch manager app: ${e}`);
                }
            }
        }

        _openSettings() {
            // Open the extension preferences in GNOME Settings
            // This requires the extension to have a prefs.js
            try {
                GLib.spawn_command_line_async(
                    'gnome-extensions prefs kgtun-manager@hamimmahmud0'
                );
            } catch (e) {
                log(`[kgtun] Failed to open settings: ${e}`);
            }
        }
    }
);

// ── Extension entry points ─────────────────────────────────────────────

let _indicator = null;

function enable() {
    _indicator = new KgtunIndicator();
    Main.panel.addToStatusArea('kgtun-indicator', _indicator, 1, 'right');
    _indicator.enable();
}

function disable() {
    if (_indicator) {
        _indicator.disable();
        _indicator.destroy();
        _indicator = null;
    }
}
