/**
 * Shuttle Assignment Dashboard JavaScript
 *
 * Handles grid slot assignment, project filtering, and modal interactions.
 * Configuration is passed via data attributes on #assignment-config element.
 */

(function() {
  'use strict';

  // Configuration from data attributes
  const configEl = document.getElementById('assignment-config');
  const assignUrl = configEl.dataset.assignUrl;
  const removeUrlTemplate = configEl.dataset.removeUrlTemplate;
  const csrfToken = configEl.dataset.csrfToken;

  // Slot data for looking up project assignments
  const slotsByProject = JSON.parse(
    document.getElementById('slots-data').textContent
  );

  // Size labels from server (avoids duplicating enum labels in JS)
  const sizeLabels = JSON.parse(
    document.getElementById('size-labels-data').textContent
  );

  // State for current modal context
  let currentSlotId = null;
  let currentSlotSize = null;
  let currentProjectIdForAssign = null;
  let currentProjectSize = null;

  // Helper to get human-readable size label (uses server-provided labels)
  function getSizeLabel(size) {
    return sizeLabels[size] || size;
  }

  // Table filtering
  function filterTable() {
    const sizeFilter = document.getElementById('size-filter').value;
    const unassignedOnly = document.getElementById('unassigned-only').checked;
    const rows = document.querySelectorAll('#projects-table tbody tr');

    rows.forEach(function(row) {
      const size = row.dataset.size;
      const assigned = row.dataset.assigned === 'true';

      let show = true;
      if (sizeFilter && size !== sizeFilter) show = false;
      if (unassignedOnly && assigned) show = false;

      row.style.display = show ? '' : 'none';
    });
  }

  // Show modal when clicking on a grid slot
  function showSlotModal(cell) {
    currentSlotId = cell.dataset.slotId;
    currentSlotSize = cell.dataset.slotSize;
    const position = cell.dataset.slotPosition;
    const projectId = cell.dataset.projectId;

    document.getElementById('modal-slot-position').textContent = position;
    document.getElementById('modal-slot-size').textContent = getSizeLabel(currentSlotSize);

    // Show/hide current project section
    const currentProjectSection = document.getElementById('modal-current-project');
    if (projectId) {
      currentProjectSection.style.display = 'block';
      const strongEl = cell.querySelector('strong');
      document.getElementById('modal-current-project-id').textContent =
        strongEl ? strongEl.textContent : projectId;
    } else {
      currentProjectSection.style.display = 'none';
    }

    // Reset project select and warning
    document.getElementById('modal-project-select').value = '';
    document.getElementById('size-mismatch-warning').style.display = 'none';

    const modal = new bootstrap.Modal(document.getElementById('slotModal'));
    modal.show();
  }

  // Show modal when clicking assign button in table
  function assignSlot(projectId, projectName, slotSize) {
    currentProjectIdForAssign = projectId;
    currentProjectSize = slotSize;

    document.getElementById('assign-modal-project-name').textContent = projectName;
    document.getElementById('assign-modal-project-size').textContent = getSizeLabel(slotSize);
    document.getElementById('assign-modal-slot-select').value = '';
    document.getElementById('assign-size-mismatch-warning').style.display = 'none';

    // Show current slot assignments
    const currentSlotsSection = document.getElementById('assign-modal-current-slots');
    const slotsList = document.getElementById('assign-modal-slots-list');
    const projectSlots = slotsByProject[projectId] || [];

    if (projectSlots.length > 0) {
      currentSlotsSection.style.display = 'block';
      slotsList.innerHTML = projectSlots.map(function(slot) {
        var isMismatch = slot.size !== slotSize;
        var badgeClass = isMismatch ? 'bg-warning' : 'bg-success';
        return '<div class="d-flex justify-content-between align-items-center mb-2">' +
          '<span class="badge ' + badgeClass + '">' + slot.position + '</span>' +
          '<span class="text-muted small">' + getSizeLabel(slot.size) +
          (isMismatch ? ' (mismatch)' : '') + '</span>' +
          '<button class="btn btn-sm btn-outline-danger" data-remove-slot-id="' + slot.id + '">' +
          'Remove</button></div>';
      }).join('');

      // Bind remove buttons
      slotsList.querySelectorAll('[data-remove-slot-id]').forEach(function(btn) {
        btn.addEventListener('click', function() {
          removeSlotFromProject(this.dataset.removeSlotId);
        });
      });
    } else {
      currentSlotsSection.style.display = 'none';
      slotsList.innerHTML = '';
    }

    const modal = new bootstrap.Modal(document.getElementById('assignModal'));
    modal.show();
  }

  // Perform the assignment API call
  function doAssignment(projectId, slotId) {
    fetch(assignUrl, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': csrfToken
      },
      body: JSON.stringify({
        project_id: projectId,
        slot_id: slotId
      })
    })
      .then(function(response) {
        if (!response.ok) {
          return response.text().then(function(text) {
            throw new Error('HTTP ' + response.status + ': ' + text);
          });
        }
        return response.json();
      })
      .then(function(data) {
        if (data.success) {
          if (data.warning) {
            alert(data.warning);
          }
          location.reload();
        } else {
          alert('Error: ' + data.error);
        }
      })
      .catch(function(error) {
        alert('Error: ' + error);
      });
  }

  // Assign project to slot (from grid click)
  function assignProject() {
    const projectSelect = document.getElementById('modal-project-select');
    const projectId = projectSelect.value;

    if (!projectId) {
      alert('Please select a project');
      return;
    }

    doAssignment(projectId, currentSlotId);
  }

  // Assign project to slot (from table click)
  function assignFromTable() {
    const slotSelect = document.getElementById('assign-modal-slot-select');
    const slotId = slotSelect.value;

    if (!slotId) {
      alert('Please select a slot');
      return;
    }

    doAssignment(currentProjectIdForAssign, slotId);
  }

  // Remove assignment from slot
  function doRemoveAssignment(slotId) {
    if (!confirm('Are you sure you want to remove this assignment?')) {
      return;
    }

    const url = removeUrlTemplate.replace('/0/', '/' + slotId + '/');
    fetch(url, {
      method: 'POST',
      headers: {
        'X-CSRFToken': csrfToken
      }
    })
      .then(function(response) {
        if (!response.ok) {
          return response.text().then(function(text) {
            throw new Error('HTTP ' + response.status + ': ' + text);
          });
        }
        return response.json();
      })
      .then(function(data) {
        if (data.success) {
          location.reload();
        } else {
          alert('Error: ' + data.error);
        }
      })
      .catch(function(error) {
        alert('Error: ' + error);
      });
  }

  // Remove assignment from slot (called from grid modal)
  function removeAssignment() {
    doRemoveAssignment(currentSlotId);
  }

  // Remove assignment from project (called from project modal)
  function removeSlotFromProject(slotId) {
    doRemoveAssignment(slotId);
  }

  // Initialize event listeners on DOM ready
  function init() {
    // Table filtering
    const sizeFilter = document.getElementById('size-filter');
    const unassignedOnly = document.getElementById('unassigned-only');
    if (sizeFilter) sizeFilter.addEventListener('change', filterTable);
    if (unassignedOnly) unassignedOnly.addEventListener('change', filterTable);

    // Grid slot cells - click and keyboard
    document.querySelectorAll('#grid-table td[data-slot-id]').forEach(function(cell) {
      cell.addEventListener('click', function() {
        showSlotModal(this);
      });
      cell.addEventListener('keydown', function(event) {
        if (event.key === 'Enter' || event.key === ' ') {
          showSlotModal(this);
          event.preventDefault();
        }
      });
    });

    // Assign buttons in project table
    document.querySelectorAll('[data-assign-project]').forEach(function(btn) {
      btn.addEventListener('click', function() {
        assignSlot(
          this.dataset.assignProject,
          this.dataset.projectName,
          this.dataset.projectSize
        );
      });
    });

    // Size mismatch warning in slot modal
    const modalProjectSelect = document.getElementById('modal-project-select');
    if (modalProjectSelect) {
      modalProjectSelect.addEventListener('change', function() {
        const selectedOption = this.options[this.selectedIndex];
        const projectSize = selectedOption.dataset.size;
        const warning = document.getElementById('size-mismatch-warning');

        if (projectSize && projectSize !== currentSlotSize) {
          warning.style.display = 'block';
        } else {
          warning.style.display = 'none';
        }
      });
    }

    // Size mismatch warning in assign modal
    const assignSlotSelect = document.getElementById('assign-modal-slot-select');
    if (assignSlotSelect) {
      assignSlotSelect.addEventListener('change', function() {
        const selectedOption = this.options[this.selectedIndex];
        const slotSize = selectedOption.dataset.size;
        const warning = document.getElementById('assign-size-mismatch-warning');

        if (slotSize && slotSize !== currentProjectSize) {
          warning.style.display = 'block';
        } else {
          warning.style.display = 'none';
        }
      });
    }

    // Assign button in slot modal
    const assignProjectBtn = document.getElementById('assign-project-btn');
    if (assignProjectBtn) {
      assignProjectBtn.addEventListener('click', assignProject);
    }

    // Assign button in project modal
    const assignFromTableBtn = document.getElementById('assign-from-table-btn');
    if (assignFromTableBtn) {
      assignFromTableBtn.addEventListener('click', assignFromTable);
    }

    // Remove assignment button in slot modal
    const removeAssignmentBtn = document.getElementById('remove-assignment-btn');
    if (removeAssignmentBtn) {
      removeAssignmentBtn.addEventListener('click', removeAssignment);
    }
  }

  // Run init when DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
