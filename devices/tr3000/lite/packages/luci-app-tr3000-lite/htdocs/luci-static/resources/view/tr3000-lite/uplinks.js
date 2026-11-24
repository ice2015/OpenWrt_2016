'use strict';
'require view';
'require fs';

function safeName(value, max, empty) {
	return typeof value === 'string' && value.length <= max && (empty || value.length > 0) && !/[^A-Za-z0-9_.-]/.test(value);
}
function ipv4(value) {
	if (typeof value !== 'string' || /[^0-9.]/.test(value)) return false;
	var octets = value.split('.');
	return octets.length === 4 && octets.every(function(octet) {
		return /^(0|[1-9][0-9]{0,2})$/.test(octet) && Number(octet) <= 255;
	});
}
function integer(value, min, max) {
	return Number.isInteger(value) && value >= min && value <= max;
}
function validate(data) {
	if (!data || data.schema_version !== 1 || [ '', 'wan', 'wwan', 'usbwan' ].indexOf(data.active) === -1 ||
		[ '', 'wan', 'wwan', 'usbwan' ].indexOf(data.previous) === -1 ||
		![ 'status_error', 'reconcile_error', 'foreign_default', 'last_event_error' ].every(function(key) { return typeof data[key] === 'boolean'; }) ||
		!Array.isArray(data.interfaces) || data.interfaces.length !== 3 || !data.usb || !data.wireless)
		throw new Error();
	data.interfaces.forEach(function(row, index) {
		var base = (index + 1) * 10;
		if (!row || row.name !== [ 'wan', 'wwan', 'usbwan' ][index] || !safeName(row.device, 15, true) ||
			!(row.address === '' || ipv4(row.address)) || !(row.gateway === '' || ipv4(row.gateway)) ||
			row.base_metric !== base || [ base, base + 1000 ].indexOf(row.effective_metric) === -1 ||
			[ 'healthy', 'unhealthy', 'unavailable', 'unknown' ].indexOf(row.health) === -1 ||
			!integer(row.failures, 0, 100) || !integer(row.successes, 0, 100) ||
			typeof row.available !== 'boolean' || !(row.link === null || typeof row.link === 'boolean'))
			throw new Error();
	});
	var usb = data.usb, wifi = data.wireless;
	if ([ 'bound', 'unavailable', 'ambiguous', 'blocked', 'error' ].indexOf(usb.state) === -1 ||
		!safeName(usb.device, 15, true) || [ '', 'rndis_host', 'cdc_ether' ].indexOf(usb.driver) === -1 ||
		![ usb.vid, usb.pid ].every(function(value) { return typeof value === 'string' && (value === '' || value.length === 4 && !/[^0-9a-f]/.test(value)); }) ||
		[ 'ap_only', 'ap_client', 'client_disconnected', 'unavailable' ].indexOf(wifi.mode) === -1 ||
		typeof wifi.error !== 'boolean' || !Array.isArray(wifi.interfaces) || wifi.interfaces.length > 32)
		throw new Error();
	wifi.interfaces.forEach(function(row) {
		if (!row || !safeName(row.section, 64, false) || !safeName(row.radio, 64, false) ||
			!safeName(row.ifname, 15, true) || !safeName(row.phy, 32, true) ||
			[ 'ap', 'sta' ].indexOf(row.mode) === -1 || row.network !== (row.mode === 'ap' ? 'lan' : 'wwan') ||
			![ 'enabled', 'up', 'shared_phy' ].every(function(key) { return typeof row[key] === 'boolean'; }) ||
			!(row.channel === null || integer(row.channel, 1, 233)) ||
			!(row.frequency === null || integer(row.frequency, 1, 65535)))
			throw new Error();
	});
	return data;
}

return view.extend({
	load: function() {
		return fs.exec('/usr/sbin/tr3000-lite-uplink-status', [ '--json' ]).then(function(result) {
			if (result.code !== 0) throw new Error();
			return validate(JSON.parse(result.stdout));
		}).catch(function() {
			throw new Error(_('Uplink status could not be read safely. Refresh or use the trusted management console.'));
		});
	},

	render: function(status) {
		var types = [ _('Ethernet WAN'), _('Wi-Fi Client'), _('USB 4G Ethernet') ];
		var warning = function(message) { return E('div', { 'class': 'alert-message warning' }, message); };
		var modes = { ap_only: _('AP-only'), ap_client: _('AP+Client'), client_disconnected: _('Disconnected Client (AP retained)'), unavailable: _('Management AP unavailable') };
		var rows = status.interfaces.map(function(row, index) {
			return E('tr', {}, [ row.name, types[index], row.device || '?',
				row.link === null ? _('Unknown') : row.link ? _('Up') : _('Down'),
				row.address || '?', row.gateway || '?', String(row.base_metric), String(row.effective_metric),
				row.health, status.active === row.name ? _('Active') : '—'
			].map(function(value) { return E('td', {}, value); }));
		});
		var radioRows = status.wireless.interfaces.map(function(row) {
			return E('tr', {}, [ row.mode === 'ap' ? _('Management AP') : _('Wi-Fi Client'), row.radio,
				row.phy || '?', row.ifname || '?', row.enabled ? _('Enabled') : _('Disabled'),
				row.up ? _('Up') : _('Down'), row.channel === null ? '?' : String(row.channel),
				row.frequency === null ? '?' : String(row.frequency)
			].map(function(value) { return E('td', {}, value); }));
		});
		var header = function(labels) { return E('tr', {}, labels.map(function(label) { return E('th', {}, label); })); };
		return E([], [
			E('h2', {}, _('Multi-uplink status')),
			E('p', {}, _('Read-only diagnostics. Priority: Ethernet WAN (10), Wi-Fi Client (20), USB 4G (30). Refresh after changes; link, DHCP/default-route availability and Internet probes are different checks.')),
			status.status_error ? warning(_('No verified snapshot is available; interface health is unknown.')) : null,
			status.reconcile_error ? warning(_('Reconciliation failed. The last verified selection may be stale; inspect the device before relying on failover.')) : null,
			status.foreign_default ? warning(_('A foreign default route takes precedence. No managed active uplink is claimed, and the foreign route is left unchanged.')) : null,
			status.last_event_error ? warning(_('The stable uplink notification failed. Remote/DDNS consumers may need inspection.')) : null,
			E('table', { 'class': 'table' }, [
				header([ _('Interface'), _('Type'), _('Device'), _('netifd link'), _('DHCP address'), _('Gateway'), _('Base metric'), _('Effective metric'), _('Health'), _('Active') ])
			].concat(rows)),
			E('h3', {}, _('USB diagnostics')),
			E('p', {}, [ _('State: '), status.usb.state, ' — ', _('Device: '), status.usb.device || '?',
				' — ', _('Driver: '), status.usb.driver || '?', ' — VID: ', status.usb.vid || '?', ' PID: ', status.usb.pid || '?' ]),
			E('p', {}, _('Only USB-parent rndis_host and cdc_ether DHCP devices are auto-claimed. Ambiguous or blocked devices require operator inspection; QMI, MBIM and NCM are not supported by this default path.')),
			E('h3', {}, _('Management AP and Wi-Fi Client')),
			E('p', {}, modes[status.wireless.mode]),
			status.wireless.error ? warning(_('Wireless runtime information is incomplete or no management AP is running. Keep a trusted console recovery path.')) : null,
			status.wireless.interfaces.some(function(row) { return row.shared_phy; }) ? warning(_('AP and Client share the same PHY or radio. The AP channel follows the Client; scanning and reconnection can briefly interrupt management.')) : null,
			E('table', { 'class': 'table' }, [
				header([ _('Role'), _('Configured radio'), _('Actual PHY'), _('Device'), _('Configuration'), _('Runtime'), _('Actual channel'), _('Frequency (MHz)') ])
			].concat(radioRows)),
			E('p', {}, _('Unknown runtime channels remain unknown; radio names are not used to infer frequency bands. Use only approved encrypted hotspots. Do not replace wireless configuration or remove the management AP.')),
			E('p', {}, [
				E('a', { 'href': L.url('admin', 'network', 'wireless') }, _('Configure Wi-Fi (standard Wireless page)')),
				' — ', E('a', { 'href': L.url('admin', 'network', 'network') }, _('Configure interfaces (standard Interfaces page)'))
			]),
			E('button', { 'class': 'cbi-button', 'click': function() { window.location.reload(); } }, _('Refresh status'))
		]);
	},

	handleSaveApply: null,
	handleSave: null,
	handleReset: null
});
