(() => {
  function addGuardianHero() {
    const wrapper = document.querySelector("#page_wrapper");

    if (!wrapper || document.querySelector("#guardian-hero")) {
      return;
    }

    const hero = document.createElement("section");
    hero.id = "guardian-hero";

    hero.innerHTML = `
      <div class="guardian-hero-top">
        <span class="guardian-brand">HG/01</span>
        <span class="guardian-label">PRIVATE INFRASTRUCTURE</span>
      </div>

      <div class="guardian-hero-main">
        <div>
          <p class="guardian-kicker">LOCAL CONTROL SURFACE</p>
          <h1>
            HOMELAB
            <span>GUARDIAN</span>
          </h1>
        </div>

        <div class="guardian-orb" aria-hidden="true"></div>
      </div>

      <div class="guardian-hero-bottom">
        <p>
          Monitorizacion, seguridad y control remoto.
          Una vista privada de toda la infraestructura.
        </p>

        <button id="guardian-explore" type="button">
          EXPLORAR SISTEMA
          <span>↘</span>
        </button>
      </div>
    `;

    wrapper.prepend(hero);

    document
      .querySelector("#guardian-explore")
      ?.addEventListener("click", () => {
        const headings = [...document.querySelectorAll("h2")];
        const target = headings.find((heading) =>
          heading.textContent.toLowerCase().includes("panel operativo"),
        );

        target?.scrollIntoView({
          behavior: "smooth",
          block: "start",
        });
      });
  }

  addGuardianHero();

  new MutationObserver(addGuardianHero).observe(document.documentElement, {
    childList: true,
    subtree: true,
  });
})();
