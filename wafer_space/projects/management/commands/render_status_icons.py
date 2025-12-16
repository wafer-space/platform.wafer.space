"""Management command to render a reference HTML file showing all status icons."""

from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand

from wafer_space.projects.models import ManufacturabilityCheck


class Command(BaseCommand):
    """Render an HTML file showing all status and result icons."""

    help = "Render HTML reference file showing all status icons (Bootstrap + ASCII)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--output",
            "-o",
            type=str,
            default="status_icons.html",
            help="Output HTML file path (default: status_icons.html)",
        )

    def handle(self, *args, **options):
        output_path = Path(options["output"])

        html_content = self._generate_html()

        output_path.write_text(html_content)
        self.stdout.write(
            self.style.SUCCESS(f"Status icons reference written to: {output_path}")
        )

    def _generate_html(self) -> str:
        """Generate the HTML content for the status icons reference."""
        # Get metadata using public class methods
        status_metadata = ManufacturabilityCheck.get_all_status_metadata()
        finished_metadata = ManufacturabilityCheck.get_all_finished_status_metadata()

        # Build execution status rows
        execution_rows = []
        for status in ManufacturabilityCheck.Status.display_order():
            meta = status_metadata.get(status, {})
            color = meta.get("color", "secondary")
            icon = meta.get("icon", "")
            unicode_icon = meta.get("unicode", "?")
            label = meta.get("label", status)

            badge = f'<span class="badge bg-{color}">'
            badge += f'<i class="bi {icon}"></i> {label}</span>'
            execution_rows.append(
                f"        <tr>\n"
                f"          <td><code>{status}</code></td>\n"
                f"          <td>{badge}</td>\n"
                f'          <td class="unicode-icon">{unicode_icon}</td>\n'
                f"          <td><code>{icon}</code></td>\n"
                f"          <td>{label}</td>\n"
                f"        </tr>"
            )

        # Build finished status rows
        finished_rows = []
        for status in ManufacturabilityCheck.FinishedStatus:
            meta = finished_metadata.get(status, {})
            color = meta.get("color", "secondary")
            icon = meta.get("icon", "")
            unicode_icon = meta.get("unicode", "?")
            label = meta.get("label", status.label)

            badge = f'<span class="badge bg-{color}">'
            badge += f'<i class="bi {icon}"></i> {label}</span>'
            finished_rows.append(
                f"        <tr>\n"
                f"          <td><code>{status.value}</code></td>\n"
                f"          <td>{badge}</td>\n"
                f'          <td class="unicode-icon">{unicode_icon}</td>\n'
                f"          <td><code>{icon}</code></td>\n"
                f"          <td>{label}</td>\n"
                f"        </tr>"
            )

        # Build the HTML document
        bootstrap_css = "https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/"
        bootstrap_css += "bootstrap.min.css"
        icons_css = "https://cdnjs.cloudflare.com/ajax/libs/bootstrap-icons/"
        icons_css += "1.11.3/font/bootstrap-icons.min.css"

        # Build icon lists for usage section
        status_icons = ", ".join(
            str(m.get("unicode", "?")) for m in status_metadata.values()
        )
        finished_icons = ", ".join(
            str(m.get("unicode", "?")) for m in finished_metadata.values()
        )

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Manufacturability Check Status Icons Reference</title>
  <link href="{bootstrap_css}" rel="stylesheet">
  <link href="{icons_css}" rel="stylesheet">
  <style>
    body {{ padding: 2rem; }}
    .unicode-icon {{ font-size: 1.5rem; text-align: center; }}
    table {{ margin-bottom: 2rem; }}
    h2 {{ margin-top: 2rem; }}
  </style>
</head>
<body>
  <div class="container">
    <h1>Manufacturability Check Status Icons</h1>
    <p class="lead">
      Reference for Bootstrap icons and their Unicode equivalents.
    </p>

    <h2>Execution Status</h2>
    <p>These statuses track the progress of a manufacturability check.</p>
    <table class="table table-striped">
      <thead>
        <tr>
          <th>Status Value</th>
          <th>Bootstrap Badge</th>
          <th>Unicode</th>
          <th>Icon Class</th>
          <th>Label</th>
        </tr>
      </thead>
      <tbody>
{chr(10).join(execution_rows)}
      </tbody>
    </table>

    <h2>Finished Status (Result)</h2>
    <p>These indicate the manufacturability result after a check completes.</p>
    <table class="table table-striped">
      <thead>
        <tr>
          <th>Status Value</th>
          <th>Bootstrap Badge</th>
          <th>Unicode</th>
          <th>Icon Class</th>
          <th>Label</th>
        </tr>
      </thead>
      <tbody>
{chr(10).join(finished_rows)}
      </tbody>
    </table>

    <h2>Usage in Code</h2>
    <pre><code># Get ASCII icon for execution status
check.status_unicode  # Returns one of: {status_icons}

# Get ASCII icon for finished result
check.finished_status_unicode  # Returns one of: {finished_icons}

# Get finished status enum
check.finished_status  # Returns FinishedStatus enum value</code></pre>
  </div>
</body>
</html>
"""
