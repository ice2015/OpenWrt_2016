'use strict';
'require view';
'require fs';
'require ui';

function isIPv4(value) {
	return typeof value === 'string' && /^(0|[1-9][0-9]{0,2})(\.(0|[1-9][0-9]{0,2})){3}$/.test(value) &&
		value.split('.').every(function(octet) { return Number(octet) <= 255; });
}

function checkMessage(check) {
	// Only local, allowlisted messages may reach the UI, never raw output.
	switch (check) {
	case 'ok': return '';
	case 'invalid_address': case 'unusable_host':
		return _('The address or prefix is invalid or is a network/broadcast address.');
	case 'management_overlap': return _('The address overlaps the management network.');
	case 'route_overlap': return _('The address overlaps an active route.');
	case 'arp_conflict_or_failure': return _('Address conflict detection failed or found an occupied address.');
	case 'management_not_initialized': case 'root_password_required':
		return _('Plant HTTPS requires a configured root password and completed management AP initialization.');
	case 'invalid_device': case 'missing_device': case 'wan_device':
		return _('The Industrial LAN device is missing or unsafe to use.');
	case 'busy': case 'firewall_busy': case 'pending_firewall_state':
		return _('Another network or firewall change is pending. Finish it before retrying.');
	case 'network_reload': case 'firewall_reload': case 'post_apply_verification':
	case 'commit_failed': case 'interrupted':
		return _('The network change could not be completed and verified.');
	case 'invalid_arguments': case 'invalid_backup': case 'backup_owner':
	case 'backup_permissions': case 'backup_pruning': case 'backup_directory':
	case 'backup_exists': case 'backup_failed': case 'candidate_cleanup':
	case 'candidate_commit': case 'candidate_copy': case 'candidate_directory':
	case 'candidate_firewall': case 'candidate_override': case 'candidate_uci':
	case 'root_required': case 'unsafe_config': case 'unsafe_path':
		return _('The controller refused the request because a safety check failed.');
	default: return null;
	}
}

function invoke(args) {
	var failure = _('Industrial LAN request failed. Refresh the page to check the current state. If recovery is incomplete, use the management network to inspect the device.');
	return fs.exec('/usr/sbin/tr3000-lite-plant', args).catch(function() {
		throw new Error(failure);
	}).then(function(result) {
		var data, message;
		try {
			data = JSON.parse(result.stdout);
			var plant = data && data.plant;
			message = data && data.checks && checkMessage(data.checks.result);
			if (!data || data.schema_version !== 1 || !plant ||
				!isIPv4(plant.address) || !isIPv4(plant.netmask) ||
				!(plant.prefix === null || (Number.isInteger(plant.prefix) && plant.prefix >= 0 && plant.prefix <= 32)) ||
				typeof plant.allow_luci !== 'boolean' || typeof plant.allow_mgmt !== 'boolean' ||
				plant.dhcp !== 'disabled' || typeof message !== 'string' ||
				typeof data.backup_id !== 'string' ||
				!(data.backup_id === '' || /^[A-Za-z0-9_-]{1,80}$/.test(data.backup_id)) ||
				[ 'none', 'restored', 'degraded' ].indexOf(data.rollback) === -1 ||
				[ 0, 2, 3 ].indexOf(result.code) === -1 ||
				(result.code === 0 ? data.checks.result !== 'ok' || data.rollback === 'degraded' : data.checks.result === 'ok'))
				throw new Error();
		} catch (error) {
			throw new Error(failure);
		}
		if (result.code !== 0) {
			if (data.rollback === 'degraded')
				message += ' ' + _('WARNING: Recovery is incomplete. Use the management network or trusted console to inspect the device before retrying.');
			else if (data.rollback === 'restored')
				message += ' ' + _('The previous settings were restored.');
			else
				message += ' ' + _('No rollback was reported. Refresh to check the current state.');
			var error = new Error(message);
			error.backupId = data.backup_id;
			throw error;
		}
		return data;
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
		var backup = E('p', { 'id': 'plant-backup', 'aria-live': 'polite' });
		showBackup(status.backup_id);
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
		function showBackup(id) {
			if (id) backup.textContent = _('Backup ID: ') + id;
		}
		function notify(error) {
			feedback.textContent = error.message;
			showBackup(error.backupId);
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
				showBackup(result.backup_id);
			}).catch(notify).finally(function() { busy = false; updateButtons(); });
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
			backup,
			E('div', { 'class': 'cbi-page-actions' }, [ validate, ' ', apply ])
		]);
	},

	handleSaveApply: null,
	handleSave: null,
	handleReset: null
});
