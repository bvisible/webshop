import frappe
from frappe.utils import now_datetime, get_datetime, formatdate, cint
from datetime import datetime
from frappe import _


def get_maintenance_context():
	"""Get context data for maintenance page"""
	context = frappe._dict()
	
	# Get maintenance settings
	settings = frappe.get_single("Webshop Settings")
	
	# Get maintenance mode based on checkboxes
	if cint(settings.maintenance_website) and cint(settings.maintenance_webshop):
		context.maintenance_mode = "Website and Webshop"
	elif cint(settings.maintenance_website):
		context.maintenance_mode = "Website and Webshop"
	elif cint(settings.maintenance_webshop):
		context.maintenance_mode = "Webshop Only"
	else:
		context.maintenance_mode = "Disabled"
	context.maintenance_message = settings.maintenance_message or _("We are currently performing scheduled maintenance. We'll be back shortly!")
	context.maintenance_end_time = settings.maintenance_end_time
	
	# Calculate time remaining if end time is set
	if context.maintenance_end_time:
		end_time = get_datetime(context.maintenance_end_time)
		now = now_datetime()
		
		if end_time > now:
			time_diff = end_time - now
			context.time_remaining = time_diff.total_seconds()
			context.formatted_end_time = formatdate(end_time, "medium") + " " + end_time.strftime("%I:%M %p")
		else:
			# Maintenance should have ended
			context.time_remaining = 0
			context.formatted_end_time = None
	else:
		context.time_remaining = None
		context.formatted_end_time = None
	
	# Add standard website context
	context.update({
		'no_cache': 1,
		'no_breadcrumbs': True,
		'no_header': True,
		'show_sidebar': False,
		'hide_login': False,
		'title': _('Under Maintenance'),
		'build_version': frappe.utils.get_build_version()
	})
	
	return context


def show_maintenance_page_direct():
	"""Show maintenance page directly using frappe.respond_as_web_page"""
	context = get_maintenance_context()
	
	# Build the maintenance page HTML
	html_content = f"""
	<div class="maintenance-container">
		<div class="maintenance-content">
			<h1>{_('Under Maintenance')}</h1>
			<p class="maintenance-message">{context.maintenance_message}</p>
			{f'<p class="maintenance-end-time">{_("Expected to be back by:")} <strong>{context.formatted_end_time}</strong></p>' if context.formatted_end_time else ''}
			{f'<div class="countdown" data-seconds="{int(context.time_remaining)}"></div>' if context.time_remaining else ''}
		</div>
	</div>
	
	<style>
		.maintenance-container {{
			display: flex;
			justify-content: center;
			align-items: center;
			min-height: 70vh;
			text-align: center;
		}}
		.maintenance-content {{
			max-width: 600px;
			padding: 2rem;
		}}
		.maintenance-message {{
			font-size: 1.2rem;
			color: #666;
			margin: 2rem 0;
		}}
		.countdown {{
			font-size: 2rem;
			color: #007bff;
			margin-top: 2rem;
		}}
	</style>
	
	<script>
		document.addEventListener('DOMContentLoaded', function() {{
			const countdownEl = document.querySelector('.countdown');
			if (countdownEl) {{
				let seconds = parseInt(countdownEl.dataset.seconds);
				
				function updateCountdown() {{
					if (seconds <= 0) {{
						window.location.reload();
						return;
					}}
					
					const hours = Math.floor(seconds / 3600);
					const minutes = Math.floor((seconds % 3600) / 60);
					const secs = seconds % 60;
					
					countdownEl.textContent = 
						(hours > 0 ? hours + 'h ' : '') +
						(minutes > 0 ? minutes + 'm ' : '') +
						secs + 's';
					
					seconds--;
				}}
				
				updateCountdown();
				setInterval(updateCountdown, 1000);
			}}
		}});
	</script>
	"""
	
	frappe.respond_as_web_page(
		_("Under Maintenance"),
		html_content,
		http_status_code=503,
		context=context
	)