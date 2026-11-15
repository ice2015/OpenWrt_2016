'use strict';
'require view';
'require fs';
'require ui';

function isIPv4(value) {
	return typeof value === 'string' && /^(0|[1-9][0-9]{0,2})(\.(0|[1-9][0-9]{0,2})){3}$/.test(value) &&
		value.split('.').every(function(octet) { return Number(octet) <= 255; });
}

function invoke(args) {
	return fs.exec('/usr/sbin/tr3000-lite-plant', args).then(function(result) {
		// Never expose controller output or transport errors to the page.
		var data = JSON.parse(result.stdout);
		var plant = data && data.plant;
		if (result.code !== 0 || data.schema_version !== 1 || !plant ||
			!isIPv4(plant.address) || !isIPv4(plant.netmask) ||
			!(plant.prefix === null || (Number.isInteger(plant.prefix) && plant.prefix >= 0 && plant.prefix <= 32)) ||
			typeof plant.allow_luci !== 'boolean' || typeof plant.allow_mgmt !== 'boolean' ||
			plant.dhcp !== 'disabled' || !data.checks || data.checks.result !== 'ok' ||
			typeof data.backup_id !== 'string' || data.rollback !== 'none')
			throw new Error();
		return data;
	}).catch(function() {
		throw new Error(_('Industrial LAN request failed. Refresh the page to check the current state. If recovery is incomplete, use the management network to inspect the device.'));
	});
}

return view.extend({
	load: function() {
		return invoke([ 'status', '--json' ]);
	},

	render: function(status) {
		var validated = null, revision = 0, busy = false;
		var address = E('input', { 'id': 'plant-address', 'type': 'text', 'class': 'cbi-input-text',
			'value': status.plant.address + '/' + (status.plant.prefix === null ? '' : status.plant.prefix) });
		var https = E('input', { 'id': 'plant-https', 'type': 'checkbox', 'checked': status.plant.allow_luci });
		var mgmt = E('input', { 'id': 'plant-mgmt', 'type': 'checkbox', 'checked': status.plant.allow_mgmt });
		var feedback = E('p', { 'role': 'status', 'aria-live': 'polite' });
		var current = E('p', {}, currentText(status.plant));
		var validate = E('button', { 'id': 'plant-validate', 'class': 'cbi-button cbi-button-action', 'click': validateAddress }, _('Validate address'));
		var apply = E('button', { 'id': 'plant-apply', 'class': 'cbi-button cbi-button-apply', 'disabled': true, 'click': applyChanges }, _('Apply'));

		function currentText(plant) {
			return _('Current address: ') + plant.address + '/' + (plant.prefix === null ? '?' : plant.prefix) +
				' — ' + _('Netmask: ') + plant.netmask;
		}
		function updateButtons() {
			validate.disabled = busy;
			apply.disabled = busy || validated !== address.value;
			https.disabled = mgmt.disabled = busy;
		}
		function invalidate() {
			revision++;
			validated = null;
			feedback.textContent = _('Validate the current address before applying.');
			updateButtons();
		}
		function notify(error) {
			ui.addNotification(null, E('p', {}, error.message), 'error');
		}
		function validateAddress() {
			if (busy) return Promise.resolve();
			invalidate();
			var candidate = address.value, requestRevision = revision;
			busy = true; updateButtons();
			return invoke([ 'validate', '--address', candidate ]).then(function() {
				if (requestRevision === revision && candidate === address.value) {
					validated = candidate;
					feedback.textContent = _('Address validated. Apply rechecks the address before changing the network.');
				}
			}).catch(notify).finally(function() { busy = false; updateButtons(); });
		}
		function applyChanges() {
			if (busy || validated === null || validated !== address.value) return Promise.resolve();
			if (!window.confirm(_('Changing the Industrial LAN address may disconnect the current session. Continue?')))
				return Promise.resolve();
			var args = [ 'apply', '--address', address.value, '--allow-luci', String(https.checked), '--allow-mgmt', String(mgmt.checked) ];
			invalidate(); busy = true; updateButtons();
			return invoke(args).then(function(result) {
				current.textContent = currentText(result.plant);
				address.value = result.plant.address + '/' + result.plant.prefix;
				https.checked = result.plant.allow_luci;
				mgmt.checked = result.plant.allow_mgmt;
				feedback.textContent = _('Industrial LAN settings applied and verified.');
			}).catch(function(error) {
				feedback.textContent = _('Apply could not be confirmed. Refresh to check the current state.');
				notify(error);
			}).finally(function() { busy = false; updateButtons(); });
		}
		address.addEventListener('input', invalidate);
		return E([], [
			E('h2', {}, _('Industrial LAN')),
			current,
			E('p', {}, _('DHCPv4, DHCPv6, RA and NDP services are permanently disabled on Industrial LAN.')),
			E('div', { 'class': 'alert-message warning' }, _('Confirm the address is unused before connecting the plant HUB. Changing the address may disconnect the current session.')),
			E('p', {}, [ E('label', { 'for': 'plant-address' }, _('IPv4 address/prefix')), ' ', address ]),
			E('p', {}, E('label', {}, [ https, ' ', _('Allow plant HTTPS management (443 only)') ])),
			E('p', {}, _('Plant HTTPS requires a configured root password and completed management AP initialization.')),
			E('p', {}, E('label', {}, [ mgmt, ' ', _('Allow management network access to plant (ICMP and TCP)') ])),
			feedback,
			E('div', { 'class': 'cbi-page-actions' }, [ validate, ' ', apply ])
		]);
	},

	handleSaveApply: null,
	handleSave: null,
	handleReset: null
});
