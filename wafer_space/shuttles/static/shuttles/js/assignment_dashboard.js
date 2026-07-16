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

  // Projects data for autocomplete
  const projectsData = JSON.parse(
    document.getElementById('projects-data').textContent
  );

  // State for current modal context
  let currentSlotId = null;
  let currentSlotSize = null;
  let currentProjectPkForAssign = null;
  let currentProjectSize = null;

  // Autocomplete state
  let filteredProjects = [];
  let activeIndex = -1;

  // Column sorting state
  let currentSortColumn = null;
  let currentSortDirection = null; // 'asc', 'desc', or null

  // Size sort order (largest to smallest)
  const sizeSortOrder = {'1x1': 0, '0p5x1': 1, '1x0p5': 2, '0p5x0p5': 3};

  // Helper to get human-readable size label (uses server-provided labels)
  function getSizeLabel(size) {
    return sizeLabels[size] || size;
  }

  // Helper to escape HTML to prevent XSS
  function escapeHtml(text) {
    var div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  // Sort the projects table by column
  function sortTable(columnIndex, sortType) {
    const table = document.getElementById('projects-table');
    const tbody = table.querySelector('tbody');
    const rows = Array.from(tbody.querySelectorAll('tr'));
    const headers = table.querySelectorAll('thead th');

    // Determine sort direction
    if (currentSortColumn === columnIndex) {
      if (currentSortDirection === 'asc') {
        currentSortDirection = 'desc';
      } else if (currentSortDirection === 'desc') {
        currentSortDirection = null;
      } else {
        currentSortDirection = 'asc';
      }
    } else {
      currentSortColumn = columnIndex;
      currentSortDirection = 'asc';
    }

    // Update sort indicators
    headers.forEach(function(header, idx) {
      const indicator = header.querySelector('.sort-indicator');
      if (indicator) {
        if (idx === columnIndex && currentSortDirection === 'asc') {
          indicator.textContent = ' ▲';
        } else if (idx === columnIndex && currentSortDirection === 'desc') {
          indicator.textContent = ' ▼';
        } else {
          indicator.textContent = '';
        }
      }
    });

    // If no direction (third click), reset to default sort: Project ID ascending
    if (!currentSortDirection) {
      sortType = 'text';
      currentSortDirection = 'asc';
      columnIndex = 0;
    }

    // Sort rows
    rows.sort(function(a, b) {
      const aCell = a.cells[columnIndex];
      const bCell = b.cells[columnIndex];

      let aVal = aCell.dataset.sortValue || aCell.textContent.trim();
      let bVal = bCell.dataset.sortValue || bCell.textContent.trim();

      let comparison = 0;

      if (sortType === 'size') {
        comparison = (sizeSortOrder[aVal] || 99) - (sizeSortOrder[bVal] || 99);
      } else if (sortType === 'status') {
        comparison = parseInt(aVal, 10) - parseInt(bVal, 10);
      } else {
        // Text sort
        comparison = aVal.localeCompare(bVal);
      }

      return currentSortDirection === 'desc' ? -comparison : comparison;
    });

    // Re-append rows in sorted order
    rows.forEach(function(row) {
      tbody.appendChild(row);
    });
  }

  // Sort projects by relevance for autocomplete
  function sortProjectsForSlot(slotSize) {
    // Priority: same size > different size
    // Within size group: manufacturable > failed > pending > assigned
    return projectsData.slice().sort(function(a, b) {
      const aSameSize = a.slot_size === slotSize;
      const bSameSize = b.slot_size === slotSize;

      // Same size first
      if (aSameSize !== bSameSize) {
        return aSameSize ? -1 : 1;
      }

      // Within same size group, sort by status
      function getPriority(proj) {
        if (proj.is_assigned) return 3;
        if (proj.latest_file_manufacturable === true) return 0;
        if (proj.latest_file_manufacturable === false) return 1;
        return 2; // pending (null)
      }

      const aPriority = getPriority(a);
      const bPriority = getPriority(b);

      if (aPriority !== bPriority) {
        return aPriority - bPriority;
      }

      // Within same priority, sort by project_id
      return a.project_id.localeCompare(b.project_id);
    });
  }

  // Filter and render autocomplete results
  function filterProjects(query, slotSize) {
    const sorted = sortProjectsForSlot(slotSize);
    const lowerQuery = query.toLowerCase();

    filteredProjects = sorted.filter(function(p) {
      return p.project_id.toLowerCase().includes(lowerQuery) ||
             p.name.toLowerCase().includes(lowerQuery);
    });

    renderAutocompleteResults(slotSize);
  }

  // Update screen reader status announcement
  function updateSearchStatus(count) {
    const statusEl = document.getElementById('project-search-status');
    if (statusEl) {
      if (count === 0) {
        statusEl.textContent = 'No matching projects found';
      } else if (count === 1) {
        statusEl.textContent = '1 project found';
      } else {
        statusEl.textContent = count + ' projects found';
      }
    }
  }

  // Render autocomplete dropdown
  function renderAutocompleteResults(slotSize) {
    const resultsDiv = document.getElementById('project-results');

    if (filteredProjects.length === 0) {
      resultsDiv.innerHTML = '<div class="autocomplete-item text-muted" role="option" aria-disabled="true">No matching projects</div>';
      resultsDiv.classList.add('show');
      document.getElementById('project-search').setAttribute('aria-expanded', 'true');
      updateSearchStatus(0);
      return;
    }

    let html = '';
    let lastSameSize = null;
    let lastStatus = null;

    filteredProjects.forEach(function(proj, index) {
      const isSameSize = proj.slot_size === slotSize;

      // Add major separator between same-size and different-size
      if (lastSameSize !== null && lastSameSize !== isSameSize) {
        html += '<div class="autocomplete-separator major">Different size</div>';
        lastStatus = null;
      }
      lastSameSize = isSameSize;

      // Add minor separator between status groups (within same size)
      const status = proj.is_assigned ? 'assigned' :
                     proj.latest_file_manufacturable === true ? 'ready' :
                     proj.latest_file_manufacturable === false ? 'failed' : 'pending';

      if (lastStatus !== null && lastStatus !== status && isSameSize) {
        html += '<div class="autocomplete-separator"></div>';
      }
      lastStatus = status;

      // Manufacturing status indicator
      const mfgText = proj.latest_file_manufacturable === true ? '✓' :
                      proj.latest_file_manufacturable === false ? '✗' : '?';
      const mfgClass = proj.latest_file_manufacturable === true ? 'mfg-pass' :
                       proj.latest_file_manufacturable === false ? 'mfg-fail' : 'mfg-pending';

      // Size badge (only for different size)
      const sizeBadge = isSameSize ? '' :
        '<span class="badge bg-secondary slot-badge ms-1">[' + getSizeLabel(proj.slot_size) + ']</span>';

      // Assigned slots display (escape each slot position for safety)
      const assignedDisplay = proj.is_assigned ?
        '<span class="text-muted ms-1">(' + proj.assigned_slots.map(escapeHtml).join(', ') + ')</span>' : '';

      html += '<div class="autocomplete-item' + (index === activeIndex ? ' active' : '') + '" ' +
              'role="option" aria-selected="' + (index === activeIndex ? 'true' : 'false') + '" ' +
              'data-index="' + index + '" data-project-pk="' + proj.pk + '">' +
              '<span class="project-id">' + escapeHtml(proj.project_id) + '</span>' +
              '<span class="' + mfgClass + '">' + mfgText + '</span> ' +
              '<span class="project-name">' + escapeHtml(proj.name) + '</span>' +
              sizeBadge + assignedDisplay +
              '</div>';
    });

    resultsDiv.innerHTML = html;
    resultsDiv.classList.add('show');
    document.getElementById('project-search').setAttribute('aria-expanded', 'true');
    updateSearchStatus(filteredProjects.length);

    // Bind click handlers
    resultsDiv.querySelectorAll('.autocomplete-item[data-project-pk]').forEach(function(item) {
      item.addEventListener('click', function() {
        selectProject(this.dataset.projectPk);
      });
    });
  }

  // Select a project from autocomplete
  function selectProject(projectPk) {
    const project = projectsData.find(function(p) { return p.pk === projectPk; });
    if (!project) return;

    document.getElementById('selected-project-pk').value = projectPk;
    document.getElementById('project-search').value = '';
    document.getElementById('project-results').classList.remove('show');
    document.getElementById('project-search').setAttribute('aria-expanded', 'false');

    // Show selected display
    const display = document.getElementById('selected-project-display');
    const badge = document.getElementById('selected-project-badge');
    const mfgText = project.latest_file_manufacturable === true ? '✓' :
                    project.latest_file_manufacturable === false ? '✗' : '?';
    badge.textContent = project.project_id + mfgText + ' - ' + project.name;
    display.style.display = 'block';

    // Check size mismatch
    const warning = document.getElementById('size-mismatch-warning');
    if (project.slot_size !== currentSlotSize) {
      warning.style.display = 'block';
    } else {
      warning.style.display = 'none';
    }

    activeIndex = -1;
  }

  // Scroll the active autocomplete item into view
  function scrollActiveItemIntoView() {
    var resultsDiv = document.getElementById('project-results');
    var activeItem = resultsDiv.querySelector('.autocomplete-item.active');
    if (activeItem) {
      activeItem.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    }
  }

  // Handle autocomplete keyboard navigation
  function handleAutocompleteKeydown(event) {
    const resultsDiv = document.getElementById('project-results');
    if (!resultsDiv.classList.contains('show')) return;

    if (event.key === 'ArrowDown') {
      event.preventDefault();
      activeIndex = Math.min(activeIndex + 1, filteredProjects.length - 1);
      renderAutocompleteResults(currentSlotSize);
      scrollActiveItemIntoView();
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      activeIndex = Math.max(activeIndex - 1, 0);
      renderAutocompleteResults(currentSlotSize);
      scrollActiveItemIntoView();
    } else if (event.key === 'Enter') {
      event.preventDefault();
      if (activeIndex >= 0 && activeIndex < filteredProjects.length) {
        selectProject(filteredProjects[activeIndex].pk);
      }
    } else if (event.key === 'Escape') {
      resultsDiv.classList.remove('show');
      document.getElementById('project-search').setAttribute('aria-expanded', 'false');
      activeIndex = -1;
    }
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

  // Select slot and submit assignment (used by grid picker in assign modal)
  function selectSlotAndSubmit(cell) {
    const slotId = cell.dataset.slotId;
    const slotSize = cell.dataset.slotSize;

    // Check if slot is already occupied
    if (cell.dataset.projectPk) {
      alert('This slot is already assigned. Please choose an empty slot.');
      return;
    }

    // Show size mismatch warning if applicable
    if (slotSize !== currentProjectSize) {
      if (!confirm('Size mismatch: Slot size does not match project size. Continue anyway?')) {
        return;
      }
    }

    doAssignment(currentProjectPkForAssign, slotId);
  }

  // Show modal when clicking on a grid slot
  function showSlotModal(cell) {
    currentSlotId = cell.dataset.slotId;
    currentSlotSize = cell.dataset.slotSize;
    const position = cell.dataset.slotPosition;
    const projectPk = cell.dataset.projectPk;

    document.getElementById('modal-slot-position').textContent = position;
    document.getElementById('modal-slot-size').textContent = getSizeLabel(currentSlotSize);

    // Show/hide current project section
    const currentProjectSection = document.getElementById('modal-current-project');
    if (projectPk) {
      currentProjectSection.style.display = 'block';
      // Look up full project info from projectsData
      var project = projectsData.find(function(p) { return p.pk === projectPk; });
      if (project) {
        document.getElementById('modal-current-project-id').textContent =
          project.project_id + ' - ' + project.name;
      } else {
        document.getElementById('modal-current-project-id').textContent = projectPk;
      }
    } else {
      currentProjectSection.style.display = 'none';
    }

    // Reset autocomplete
    document.getElementById('project-search').value = '';
    document.getElementById('selected-project-pk').value = '';
    document.getElementById('selected-project-display').style.display = 'none';
    document.getElementById('project-results').classList.remove('show');
    document.getElementById('project-search').setAttribute('aria-expanded', 'false');
    document.getElementById('size-mismatch-warning').style.display = 'none';
    activeIndex = -1;

    // Pre-populate filtered list
    filterProjects('', currentSlotSize);

    const modal = new bootstrap.Modal(document.getElementById('slotModal'));
    modal.show();
  }

  // Show modal when clicking assign button in table
  function assignSlot(projectPk, projectName, slotSize) {
    currentProjectPkForAssign = projectPk;
    currentProjectSize = slotSize;

    document.getElementById('assign-modal-project-name').textContent = projectName;
    document.getElementById('assign-modal-project-size').textContent = getSizeLabel(slotSize);

    // Show current slot assignments
    const currentSlotsSection = document.getElementById('assign-modal-current-slots');
    const slotsList = document.getElementById('assign-modal-slots-list');
    const projectSlots = slotsByProject[projectPk] || [];

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

    // Reinitialize grid click handlers for the modal grid
    const modalGrid = document.getElementById('assign-modal-grid');
    if (modalGrid) {
      modalGrid.querySelectorAll('td[data-slot-id]').forEach(function(cell) {
        // Remove old listeners by cloning
        var newCell = cell.cloneNode(true);
        cell.parentNode.replaceChild(newCell, cell);

        // Add new listener
        newCell.addEventListener('click', function() {
          selectSlotAndSubmit(this);
        });
        newCell.addEventListener('keydown', function(event) {
          if (event.key === 'Enter' || event.key === ' ') {
            selectSlotAndSubmit(this);
            event.preventDefault();
          }
        });
      });
    }

    const modal = new bootstrap.Modal(document.getElementById('assignModal'));
    modal.show();

    // Highlight matching-size slots in the modal grid
    highlightSlotsBySize(slotSize, 'assign-modal-grid-table');

    // Highlight assigned slots for this project in the modal grid
    var positions = projectSlots.map(function(s) { return s.position; });
    highlightAssignedSlots(positions, 'assign-modal-grid-table');
  }

  // Perform the assignment API call
  function doAssignment(projectPk, slotId) {
    fetch(assignUrl, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': csrfToken
      },
      body: JSON.stringify({
        project_pk: projectPk,
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
            alert('Warning: ' + data.warning);
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
    const projectPk = document.getElementById('selected-project-pk').value;

    if (!projectPk) {
      alert('Please select a project');
      return;
    }

    doAssignment(projectPk, currentSlotId);
  }

  // Remove assignment from slot
  function doRemoveAssignment(slotId) {
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

  // Highlight all slots matching a given size (on main grid)
  function highlightSlotsBySize(size, gridId) {
    gridId = gridId || 'grid-table';
    var grid = document.getElementById(gridId);
    grid.querySelectorAll('td[data-slot-size]').forEach(function(cell) {
      if (cell.dataset.slotSize === size) {
        cell.classList.add('slot-highlight-size');
      }
    });
  }

  // Highlight specific slots by their positions (e.g., ['A1', 'B2'])
  function highlightAssignedSlots(positions, gridId) {
    gridId = gridId || 'grid-table';
    var grid = document.getElementById(gridId);
    grid.querySelectorAll('td[data-slot-position]').forEach(function(cell) {
      if (positions.indexOf(cell.dataset.slotPosition) !== -1) {
        cell.classList.add('slot-highlight-assigned');
      }
    });
  }

  // Clear all highlights from a grid
  function clearSlotHighlights(gridId) {
    gridId = gridId || 'grid-table';
    var grid = document.getElementById(gridId);
    grid.querySelectorAll('.slot-highlight-size, .slot-highlight-assigned').forEach(function(cell) {
      cell.classList.remove('slot-highlight-size', 'slot-highlight-assigned');
    });
  }

  // Initialize event listeners on DOM ready
  function init() {
    // Table filtering
    const sizeFilter = document.getElementById('size-filter');
    const unassignedOnly = document.getElementById('unassigned-only');
    if (sizeFilter) sizeFilter.addEventListener('change', filterTable);
    if (unassignedOnly) unassignedOnly.addEventListener('change', filterTable);

    // Column sorting
    document.querySelectorAll('#projects-table thead th[data-sortable]').forEach(function(header, index) {
      header.addEventListener('click', function() {
        const sortType = this.dataset.sortType || 'text';
        sortTable(index, sortType);
      });
    });

    // Grid slot cells - click and keyboard (using configurable handler)
    document.querySelectorAll('#grid-table td[data-slot-id]').forEach(function(cell) {
      var handlerName = cell.dataset.clickHandler;
      var handler = window[handlerName];
      if (handler) {
        cell.addEventListener('click', function() {
          handler(this);
        });
        cell.addEventListener('keydown', function(event) {
          if (event.key === 'Enter' || event.key === ' ') {
            handler(this);
            event.preventDefault();
          }
        });
      }
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

    // Highlight slots on project table row hover
    document.querySelectorAll('#projects-table tbody tr').forEach(function(row) {
      row.addEventListener('mouseenter', function() {
        var size = this.dataset.size;
        if (size) {
          highlightSlotsBySize(size);
        }

        // Also highlight assigned slots for this project
        var assignBtn = this.querySelector('[data-assign-project]');
        if (assignBtn) {
          var projectPk = assignBtn.dataset.assignProject;
          var slots = slotsByProject[projectPk] || [];
          var positions = slots.map(function(s) { return s.position; });
          highlightAssignedSlots(positions);
        }
      });
      row.addEventListener('mouseleave', function() {
        clearSlotHighlights();
      });
    });

    // Highlight slots on summary table row hover
    document.querySelectorAll('#summary-table-body tr').forEach(function(row) {
      row.addEventListener('mouseenter', function() {
        var size = this.dataset.size;
        if (size) {
          highlightSlotsBySize(size);
        }
      });
      row.addEventListener('mouseleave', function() {
        clearSlotHighlights();
      });
    });

    // Autocomplete input
    const projectSearch = document.getElementById('project-search');
    if (projectSearch) {
      projectSearch.addEventListener('input', function() {
        filterProjects(this.value, currentSlotSize);
      });
      projectSearch.addEventListener('focus', function() {
        filterProjects(this.value, currentSlotSize);
      });
      projectSearch.addEventListener('keydown', handleAutocompleteKeydown);
    }

    // Clear project selection
    const clearBtn = document.getElementById('clear-project-selection');
    if (clearBtn) {
      clearBtn.addEventListener('click', function() {
        document.getElementById('selected-project-pk').value = '';
        document.getElementById('selected-project-display').style.display = 'none';
        document.getElementById('size-mismatch-warning').style.display = 'none';
        document.getElementById('project-search').focus();
      });
    }

    // Close autocomplete when clicking outside
    document.addEventListener('click', function(event) {
      const resultsDiv = document.getElementById('project-results');
      const searchInput = document.getElementById('project-search');
      if (resultsDiv && searchInput &&
          !resultsDiv.contains(event.target) &&
          event.target !== searchInput) {
        resultsDiv.classList.remove('show');
        searchInput.setAttribute('aria-expanded', 'false');
      }
    });

    // Assign button in slot modal
    const assignProjectBtn = document.getElementById('assign-project-btn');
    if (assignProjectBtn) {
      assignProjectBtn.addEventListener('click', assignProject);
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

  // Expose functions for grid click handlers
  window.showSlotModal = showSlotModal;
  window.selectSlotAndSubmit = selectSlotAndSubmit;
})();
