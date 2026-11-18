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
	case 'management_overlap': return _('The address overlaps the access network.');
	case 'route_overlap': return _('The address overlaps an active route.');
	case 'arp_conflict_or_failure': return _('Address conflict detection failed or found an occupied address.');
	case 'management_not_initialized':
		return _('The management AP is not ready. Use the wired access segment or wait until the AP is up.');
	case 'root_password_required':
		return _('A non-empty root password is required.');
	case 'already_plant_mode': return _('The device already runs in industrial mode.');
	case 'already_lan_mode': return _('The device already runs in access mode.');
	case 'no_lan_port': return _('The access segment has no wired port to hand over.');
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
			if (!data || data.schema_version !== 2 || !plant ||
				!isIPv4(plant.address) || !isIPv4(plant.netmask) ||
				!(plant.prefix === null || (Number.isInteger(plant.prefix) && plant.prefix >= 0 && plant.prefix <= 32)) ||
				typeof plant.allow_luci !== 'boolean' || typeof plant.allow_mgmt !== 'boolean' ||
				plant.dhcp !== 'disabled' || typeof message !== 'string' ||
				[ 'lan', 'plant' ].indexOf(data.mode) === -1 ||
				!data.lan || typeof data.lan.cidr !== 'string' || typeof data.lan.dhcp_pool !== 'string' ||
				typeof data.ap_ready !== 'boolean' || typeof data.legacy_config_detected !== 'boolean' ||
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
		var industrial = status.mode === 'plant';
		var mode = E('p', { 'id': 'plant-mode' }, _('Mode: ') +
			(industrial ? _('Industrial mode (LAN port belongs to the plant segment)') :
				_('Access mode (LAN port serves the operator access segment)')));
		var access = E('p', { 'id': 'lan-access' }, _('Access segment: ') + status.lan.cidr +
			' — ' + _('DHCP pool: ') + status.lan.dhcp_pool);
		var ap = E('p', { 'id': 'lan-ap' }, _('Management AP: ') +
			(status.ap_ready ? _('ready') : _('not ready')));
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
		var enable = E('button', { 'id': 'plant-enable', 'class': 'cbi-button cbi-button-action', 'click': enablePlant }, _('Enable industrial mode'));
		var disable = E('button', { 'id': 'plant-disable', 'class': 'cbi-button cbi-button-action', 'click': disablePlant }, _('Return to access mode'));
		var legacy = status.legacy_config_detected ?
			E('div', { 'class': 'alert-message error', 'id': 'plant-legacy' },
				_('This configuration predates the access segment. Reflash without preserving settings (sysupgrade -n) before using the industrial features.')) : null;

		function currentText(plant) {
			return _('Current address: ') + plant.address + '/' + (plant.prefix === null ? '?' : plant.prefix) +
				' — ' + _('Netmask: ') + plant.netmask;
		}
		function updateButtons() {
			validate.disabled = busy || !industrial;
			apply.disabled = busy || !industrial || validated !== address.value;
			https.disabled = mgmt.disabled = busy || !industrial;
			enable.disabled = busy || industrial || !status.ap_ready;
			disable.disabled = busy || !industrial;
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
		function enablePlant() {
			if (busy) return Promise.resolve();
			if (!window.confirm(_('Handing the only LAN port to the industrial segment removes the wired management path. Continue?')))
				return Promise.resolve();
			busy = true; updateButtons();
			return invoke([ 'enable-plant', '--address', address.value ]).then(function(result) {
				feedback.textContent = _('Industrial mode enabled and verified. Refresh the page to see the new state.');
				showBackup(result.backup_id);
			}).catch(notify).finally(function() { busy = false; updateButtons(); });
		}
		function disablePlant() {
			if (busy) return Promise.resolve();
			if (!window.confirm(_('Returning to access mode gives the LAN port back to the operator access segment. Continue?')))
				return Promise.resolve();
			busy = true; updateButtons();
			return invoke([ 'disable-plant' ]).then(function(result) {
				feedback.textContent = _('Access mode restored and verified. Refresh the page to see the new state.');
				showBackup(result.backup_id);
			}).catch(notify).finally(function() { busy = false; updateButtons(); });
		}
		address.addEventListener('input', invalidate);
		updateButtons();
		return E([], [
			E('h2', {}, _('Industrial LAN')),
			mode,
			access,
			ap,
			legacy,
			current,
			E('p', {}, _('DHCPv4, DHCPv6, RA and NDP services are permanently disabled on Industrial LAN.')),
			E('div', { 'class': 'alert-message warning' }, _('Confirm the address is unused before connecting the plant HUB. Changing the address may disconnect the current session.')),
			E('p', {}, [ E('label', { 'for': 'plant-address' }, _('IPv4 address/prefix')), ' ', address ]),
			E('p', {}, E('label', {}, [ https, ' ', _('Allow plant HTTPS management (443 only)') ])),
			E('p', {}, _('Plant HTTPS requires a configured root password.')),
			E('p', {}, E('label', {}, [ mgmt, ' ', _('Allow access network access to plant (ICMP and TCP)') ])),
			E('h3', {}, _('Optional Wi-Fi Client uplink')),
			E('p', {}, _('AP-only, AP+Client and disconnected Client configurations keep the management AP configured. No default Client profile or automatic open-network join is provided.')),
			E('div', { 'class': 'alert-message warning' }, _('When AP and Client use the same radio, the AP channel follows the Client; scanning or reconnecting may briefly interrupt management. Use an encrypted, explicitly approved hotspot. Never select “Replace wireless configuration”, delete the management AP, or disable its radio.')),
			E('p', {}, _('Join the approved hotspot on the standard Wireless page, use the wwan network and WAN firewall zone, then enable wwan automatic startup on the standard Interfaces page. Interface wwan is DHCP with metric 20 and starts disabled.')),
			E('p', {}, [
				E('a', { 'href': L.url('admin', 'network', 'wireless') }, _('Configure Wi-Fi Client (standard Wireless page)')),
				' — ',
				E('a', { 'href': L.url('admin', 'network', 'network') }, _('Configure interfaces (standard Interfaces page)'))
			]),
			feedback,
			backup,
			E('div', { 'class': 'cbi-page-actions' }, [ validate, ' ', apply, ' ', enable, ' ', disable ])
		]);
	},

	handleSaveApply: null,
	handleSave: null,
	handleReset: null
});
