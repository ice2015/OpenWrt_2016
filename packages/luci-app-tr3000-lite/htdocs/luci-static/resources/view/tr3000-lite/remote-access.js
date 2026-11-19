'use strict';
'require view';
'require fs';
'require ui';

function isIPv4(value) {
	return typeof value === 'string' && /^(0|[1-9][0-9]{0,2})(\.(0|[1-9][0-9]{0,2})){3}$/.test(value) &&
		value.split('.').every(function(octet) { return Number(octet) <= 255; });
}

function safeStr(val, maxLen) {
	return typeof val === 'string' && val.length <= (maxLen || 128) && !/[^A-Za-z0-9_.:/-]/.test(val);
}

function validateRemote(data) {
	if (!data || data.schema_version !== 1 || typeof data.enrolled !== 'boolean' ||
		!data.gates || !data.roles || !data.policy || !data.effective ||
		!data.sources || !data.plant || !data.checks || typeof data.degraded !== 'boolean')
		throw new Error();
	return data;
}

function validateDDNS(data) {
	if (!data || data.schema_version !== 1 || typeof data.configured !== 'boolean' ||
		typeof data.enabled !== 'boolean' || typeof data.direct_candidate !== 'boolean')
		throw new Error();
	return data;
}

return view.extend({
	load: function() {
		return Promise.all([
			fs.exec('/usr/sbin/tr3000-lite-remote', ['status', '--json']),
			fs.exec('/usr/sbin/tr3000-lite-ddns-status', ['--json'])
		]).then(function(results) {
			var remoteRes = results[0];
			var ddnsRes = results[1];
			if (remoteRes.code !== 0 || ddnsRes.code !== 0) throw new Error();
			return {
				remote: validateRemote(JSON.parse(remoteRes.stdout)),
				ddns: validateDDNS(JSON.parse(ddnsRes.stdout))
			};
		}).catch(function() {
			throw new Error(_('Remote access status could not be read safely. Refresh or inspect the device via management network.'));
		});
	},

	render: function(data) {
		var remote = data.remote;
		var ddns = data.ddns;
		var plantCidr = remote.plant.cidr || '192.168.20.0/24';

		var directIp = remote.roles.wg_direct.address || '10.10.1.1/32';
		var vpsIp = remote.roles.wg_vps.address || '10.20.1.2/32';

		var directAllowedIPs = directIp + ', ' + plantCidr;
		var vpsAllowedIPs = vpsIp + ', ' + plantCidr;

		var gatesOk = remote.enrolled && remote.gates.root_password && remote.gates.ap_initialized && remote.gates.identity && remote.gates.keys;

		var directSources = (remote.sources.direct || []).join(', ') || _('None');
		var vpsSources = (remote.sources.vps || []).join(', ') || _('None');

		var luciSwitch = E('input', {
			type: 'checkbox',
			id: 'allow_luci_cb',
			checked: remote.effective.allow_luci ? 'checked' : null,
			disabled: gatesOk ? null : 'disabled'
		});

		var plantSwitch = E('input', {
			type: 'checkbox',
			id: 'allow_plant_cb',
			checked: remote.effective.allow_plant ? 'checked' : null,
			disabled: gatesOk ? null : 'disabled'
		});

		var applyBtn = E('button', {
			'class': 'cbi-button cbi-button-apply',
			'disabled': gatesOk ? null : 'disabled',
			'click': function(ev) {
				var newLuci = document.getElementById('allow_luci_cb').checked;
				var newPlant = document.getElementById('allow_plant_cb').checked;
				ui.showModal(_('Applying remote policy'), [
					E('p', {}, _('Synchronizing remote authorization rules...'))
				]);
				fs.exec('/usr/sbin/tr3000-lite-remote', [
					'set-policy',
					'--allow-luci', newLuci ? 'true' : 'false',
					'--allow-plant', newPlant ? 'true' : 'false'
				]).then(function(res) {
					ui.hideModal();
					if (res.code === 0) {
						window.location.reload();
					} else {
						ui.addNotification(null, E('p', {}, _('Policy update failed: ') + (res.stderr || res.stdout)));
					}
				}).catch(function(err) {
					ui.hideModal();
					ui.addNotification(null, E('p', {}, _('Error invoking remote controller: ') + err.message));
				});
			}
		}, _('Save & Apply Policy'));

		return E('div', { 'class': 'cbi-map' }, [
			E('h2', {}, _('TR3000 Lite Dual Remote Access')),
			E('div', { 'class': 'cbi-map-descr' }, _('Conditional Direct Cloudflare-DDNS WireGuard access and resilient outbound VPS tunnel.')),

			E('div', { 'class': 'alert-message warning' }, [
				E('strong', {}, _('Operating Warning: ')),
				_('Direct and VPS client profiles share the same plant route. Do NOT activate both profiles simultaneously on the Windows client.')
			]),

			E('fieldset', { 'class': 'cbi-section' }, [
				E('legend', {}, _('Enrollment & Gate Status')),
				E('table', { 'class': 'table' }, [
					E('tr', {}, [ E('th', {}, _('Device Identity')), E('td', {}, remote.identity || _('Unenrolled')) ]),
					E('tr', {}, [ E('th', {}, _('Enrollment Status')), E('td', {}, remote.enrolled ? _('Enrolled') : _('Unenrolled / Pending Staging')) ]),
					E('tr', {}, [ E('th', {}, _('Root Password Set')), E('td', {}, remote.gates.root_password ? _('Yes') : _('No (Required for Remote LuCI)')) ]),
					E('tr', {}, [ E('th', {}, _('AP Initialized')), E('td', {}, remote.gates.ap_initialized ? _('Yes') : _('No')) ]),
					E('tr', {}, [ E('th', {}, _('Device Keys Present')), E('td', {}, remote.gates.keys ? _('Yes') : _('No')) ])
				])
			]),

			E('fieldset', { 'class': 'cbi-section' }, [
				E('legend', {}, _('Tunnel Status & Client AllowedIPs')),
				E('table', { 'class': 'table' }, [
					E('tr', {}, [ E('th', {}, _('Direct WG Router IP')), E('td', {}, directIp) ]),
					E('tr', {}, [ E('th', {}, _('Direct DDNS Hostname')), E('td', {}, ddns.hostname || _('Unconfigured')) ]),
					E('tr', {}, [ E('th', {}, _('Direct Candidacy (Public IPv4)')), E('td', {}, ddns.direct_candidate ? _('Yes') : _('No (CGNAT / Private WAN)')) ]),
					E('tr', {}, [ E('th', {}, _('Direct Client AllowedIPs')), E('td', {}, E('code', {}, directAllowedIPs)) ]),
					E('tr', {}, [ E('th', {}, _('Direct Authorized /32 Peers')), E('td', {}, directSources) ]),
					E('tr', {}, [ E('th', {}, _('VPS WG Router IP')), E('td', {}, vpsIp) ]),
					E('tr', {}, [ E('th', {}, _('VPS Client AllowedIPs')), E('td', {}, E('code', {}, vpsAllowedIPs)) ]),
					E('tr', {}, [ E('th', {}, _('VPS Authorized /32 Sources')), E('td', {}, vpsSources) ])
				])
			]),

			E('fieldset', { 'class': 'cbi-section' }, [
				E('legend', {}, _('Remote Policy Switches')),
				E('div', { 'class': 'cbi-value' }, [
					E('label', { 'class': 'cbi-value-title' }, _('Allow Remote LuCI (HTTPS 443)')),
					E('div', { 'class': 'cbi-value-field' }, [ luciSwitch ])
				]),
				E('div', { 'class': 'cbi-value' }, [
					E('label', { 'class': 'cbi-value-title' }, _('Allow Plant Industrial Access & SNAT')),
					E('div', { 'class': 'cbi-value-field' }, [ plantSwitch ])
				]),
				E('div', { 'class': 'cbi-page-actions' }, [ applyBtn ])
			])
		]);
	},

	handleSaveApply: null,
	handleSave: null,
	handleReset: null
});
