"""Page Object for the My Projects list."""

from selenium.webdriver.common.by import By

from tests.browser.pages.base_page import BasePage

# Every badge in a row must lie inside its own column (the row's direct
# child) and that column must not scroll sideways. Returns one line per
# badge that does not, so a failure names the badge and by how much.
BADGES_OUTSIDE_COLUMN_JS = """
const problems = [];
document.querySelectorAll('[data-project-row]').forEach((row) => {
  row.querySelectorAll(':scope > div').forEach((column) => {
    const box = column.getBoundingClientRect();
    column.querySelectorAll('.badge').forEach((badge) => {
      const rect = badge.getBoundingClientRect();
      const over = Math.max(rect.right - box.right, box.left - rect.left);
      if (over > 0.5) {
        problems.push(`"${badge.textContent.trim()}" is ${over.toFixed(1)}px outside`);
      }
    });
    if (column.scrollWidth > column.clientWidth) {
      problems.push(`column of "${column.textContent.trim().slice(0, 30)}" overflows`);
    }
  });
});
return problems;
"""


class ProjectListPage(BasePage):
    """The My Projects list at /projects/."""

    PATH = "/projects/"
    ROWS = (By.CSS_SELECTOR, "[data-project-row]")
    COMPACT_COUNTDOWNS = (By.CSS_SELECTOR, "[data-countdown-compact]")
    SHUTTLE_COLUMNS = (By.CSS_SELECTOR, "[data-shuttle-column]")

    def open(self):
        self.navigate_to(self.PATH)
        self.find_elements(self.ROWS)
        self.wait.until(
            lambda d: d.execute_script("return document.readyState") == "complete",
        )
        return self

    def compact_countdown_texts(self) -> list[str]:
        return [el.text for el in self.driver.find_elements(*self.COMPACT_COUNTDOWNS)]

    def badges_outside_their_column(self) -> list[str]:
        """Badges that run out of their column, with how far (empty when fine)."""
        return self.driver.execute_script(BADGES_OUTSIDE_COLUMN_JS)

    def shuttle_column_lefts_and_widths(self) -> set[tuple[int, int]]:
        """Distinct (left, width) of the shuttle column over all rows."""
        return {
            (round(el.rect["x"]), round(el.rect["width"]))
            for el in self.driver.find_elements(*self.SHUTTLE_COLUMNS)
        }
