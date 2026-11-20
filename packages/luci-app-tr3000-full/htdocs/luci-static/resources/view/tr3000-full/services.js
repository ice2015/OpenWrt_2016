'use strict';
'require view';
'require fs';
'require ui';

var controller = '/usr/sbin/tr3000-full-service';
var services = [
	{ id: 'wireguard', title: _('WireGuard tunnel'), note: _('Inbound access to the home LAN. Configure the wg interface and enable the firewall rules first.') },
	{ id: 'tailscale', title: _('Tailscale'), note: _('Optional backup remote channel. Configure ACLs before enabling.') },
	{ id: 'homeproxy', title: _('HomeProxy (sing-box)'), note: _('Configure nodes and routing mode in Services → HomeProxy.') },
	{ id: 'cloudflared', title: _('Cloudflare Tunnel'), note: _('Expose only Access-protected web applications.') }
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
			// LuCI renders every attribute through setAttribute, so a boolean
			// "disabled: false" would still emit the HTML disabled attribute
			// and leave the button inert. Only omit or set the attribute.
			var attributes = {
				'class': action === 'enable' ? 'cbi-button cbi-button-apply' : 'cbi-button cbi-button-reset',
				'click': ui.createHandlerFn(this, invoke, action, service.id)
			};
			if (!state.installed) attributes.disabled = 'disabled';
			return E('tr', {}, [
				E('td', { 'class': 'td left' }, [ E('strong', {}, service.title), E('br'), E('small', {}, service.note) ]),
				E('td', { 'class': 'td' }, label),
				E('td', { 'class': 'td right' }, E('button', attributes,
					action === 'enable' ? _('Enable') : _('Disable')))
			]);
		}, this);

		return E([], [
			E('h2', {}, _('TR3000 Full remote services')),
			status.legacy_config_detected ? E('div', { 'class': 'alert-message danger' },
				_('Legacy industrial configuration detected. Reflash without keeping settings (sysupgrade -n).')) : E([]),
			E('div', { 'class': 'alert-message warning' },
				_('All remote services are disabled by default. Enabling a tunnel does not open the WAN management plane.')),
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
