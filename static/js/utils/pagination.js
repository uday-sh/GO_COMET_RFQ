export function renderPagination(container, { page, pageSize, total, onPage }) {
  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  container.classList.toggle("hidden", total <= pageSize);
  container.innerHTML = `<span>Page ${page} of ${pageCount} · ${total} results</span><div class="pagination-actions"><button class="button button-quiet" type="button" data-page="${page - 1}" ${page <= 1 ? "disabled" : ""}>← Previous</button><button class="button button-quiet" type="button" data-page="${page + 1}" ${page >= pageCount ? "disabled" : ""}>Next →</button></div>`;
  container.querySelectorAll("[data-page]").forEach((button) => {
    button.addEventListener("click", () => onPage(Number(button.dataset.page)));
  });
}
