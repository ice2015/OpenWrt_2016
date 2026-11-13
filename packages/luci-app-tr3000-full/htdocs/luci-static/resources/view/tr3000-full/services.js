'use strict';
'require view';
'require fs';
'require ui';

var controller = '/usr/sbin/tr3000-full-service';
var services = [
	{ id: 'wireguard', title: _('WireGuard tunnel'), note: _('Plant access still requires explicit peer, destination and port authorization.') },
	{ id: 'tailscale', title: _('Tailscale'), note: _('Configure ACLs and approved routes before enabling.') },
	{ id: 'sing-box', title: _('sing-box'), note: _('Industrial, management and VPN endpoint traffic must remain excluded.') },
	{ id: 'cloudflared', title: _('Cloudflare Tunnel'), note: _('Expose only Access-protected web applications, never PLC control ports.') }
];

function invoke(action, service) {
	return fs.exec(controller, [ action, service ]).then(function(result) {
		if (result.code !== 0)
			throw new Error(result.stderr || _('Service action failed'));
		window.location.reload();
	}).catch(function(error) {
		ui.addNotification(null, E('p', {}, error.message || String(error)), 'error');
	});
}

return view.extend({
	load: function() {
		return fs.exec(controller, [ 'status', '--json' ]).then(function(result) {
			if (result.code !== 0)
				throw new Error(result.stderr || _('Unable to read service status'));
			return JSON.parse(result.stdout);
		});
	},

	render: function(status) {
		var rows = services.map(function(service) {
			var state = status[service.id] || { installed: false, enabled: false, running: false };
			var label = !state.installed
				? _('Not included in this build')
				: (state.running ? _('Running') : _('Stopped'));
			var action = state.enabled || state.running ? 'disable' : 'enable';
			return E('tr', {}, [
				E('td', { 'class': 'td left' }, [ E('strong', {}, service.title), E('br'), E('small', {}, service.note) ]),
				E('td', { 'class': 'td' }, label),
				E('td', { 'class': 'td right' }, E('button', {
					'class': action === 'enable' ? 'cbi-button cbi-button-apply' : 'cbi-button cbi-button-reset',
					'disabled': !state.installed,
					'click': ui.createHandlerFn(this, invoke, action, service.id)
				}, action === 'enable' ? _('Enable') : _('Disable')))
			]);
		}, this);

		return E([], [
			E('h2', {}, _('TR3000 Full remote services')),
			E('div', { 'class': 'alert-message warning' },
				_('All remote services are disabled by default. Enabling a tunnel does not grant access to the plant network.')),
			E('table', { 'class': 'table' }, [
				E('tr', { 'class': 'tr table-titles' }, [
					E('th', { 'class': 'th' }, _('Service')),
					E('th', { 'class': 'th' }, _('Status')),
					E('th', { 'class': 'th' }, _('Action'))
				])
			].concat(rows))
		]);
	},

	handleSaveApply: null,
	handleSave: null,
	handleReset: null
});
