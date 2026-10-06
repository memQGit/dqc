// Rebind the copy control when Material replaces a page during navigation.
document$.subscribe(() => {
  document.querySelectorAll(".mcp-setup-copy").forEach((button) => {
    const prompt = document.getElementById(button.dataset.copyTarget);
    const card = button.closest(".mcp-setup-card");
    const select = card.querySelector(".mcp-setup-agent");
    const status = card.querySelector(".mcp-setup-status");
    const label = button.querySelector(".mcp-setup-copy__label");
    const render = () => {
      const client = select.selectedOptions[0].textContent;
      const target = select.value === "other" ? "your MCP client" : client;
      const common = document.getElementById("mcp-setup-common").content.textContent;
      const steps = document.getElementById(`mcp-setup-${select.value}`).content.textContent;
      prompt.textContent = common
        .replace("{{CLIENT}}", target)
        .replace("{{CLIENT_STEPS}}", steps);
      label.textContent = `Copy ${client} prompt`;
      button.setAttribute("aria-label", label.textContent);
      status.textContent = "Copy, paste into your agent, and send.";
    };
    select.onchange = render;
    render();
    button.onclick = async () => {
      button.disabled = true;
      select.disabled = true;
      try {
        await navigator.clipboard.writeText(prompt.textContent);
        label.textContent = "Copied!";
        status.textContent = "Paste into your agent and send.";
      } catch {
        prompt.closest("details").open = true;
        label.textContent = `Copy ${select.selectedOptions[0].textContent} prompt`;
        status.textContent =
          "Copy unavailable. Select and copy the full prompt below.";
      } finally {
        button.disabled = false;
        select.disabled = false;
      }
    };
  });
});
