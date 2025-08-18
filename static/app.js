(function() {
  const $ = (sel) => document.querySelector(sel);

  const form = $("#calc-form");
  const result = $("#result");
  const rates = $("#rates");

  function payloadFromForm() {
    const v = (id) => document.getElementById(id).value;

    const coBorrowerStatus = v("b2_status");
    const hasCo = coBorrowerStatus !== "aucun";
    const borrowersCount = hasCo ? 2 : 1;

    // V1: uniquement "cdi" ou "cdd"
    const b1_status = v("b1_status"); // "cdi" | "cdd"
    const b2_status = hasCo ? v("b2_status") : null; // "cdi" | "cdd"

    return {
      project: {
        property_price: parseFloat(v("property_price")),
        property_type: v("property_type"),                // "ancien" | "neuf"
        personal_contribution: parseFloat(v("personal_contribution")),
        loan_duration: parseInt(v("loan_duration"), 10)   // entre 5 et 30
      },
      household: {
        borrowers_count: borrowersCount,                  // requis
        main_borrower: {
          employment: {
            status: b1_status,
            net_monthly_income: parseFloat(v("b1_income")),
            years_experience: parseFloat(v("b1_years")),
            trial_period: false
          },
          age: parseInt(v("b1_age"), 10)
        },
        co_borrower: hasCo ? {
          employment: {
            status: b2_status,
            net_monthly_income: parseFloat(v("b2_income")),
            years_experience: parseFloat(v("b2_years")),
            trial_period: false
          },
          age: parseInt(v("b2_age"), 10)
        } : null,
        children: parseInt(v("children"), 10)
      },
      // Requis par l'API V1 (valeurs par défaut sûres)
      housing: {
        current_status: "locataire",      // "locataire" | "proprietaire" | "heberge_gratuit"
        monthly_rent: 0,
        current_mortgage: 0,
        changing_main_residence: true
      },
      // Requis par l'API V1 (valeurs par défaut sûres)
      financial: {
        consumer_loans: [],               // liste vide par défaut
        rental_income: 0,
        other_income: 0
      }
    };
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    result.style.display = "none";
    try {
      const payload = payloadFromForm();
      const resp = await fetch("/api/evaluate", {
        method: "POST",
        headers: {"Content-Type":"application/json"},
        body: JSON.stringify(payload)
      });

      const data = await resp.json();

      if (!resp.ok) {
        // Affiche l'erreur de validation Pydantic proprement
        result.textContent = "Erreur (" + resp.status + "): " + JSON.stringify(data, null, 2);
        result.style.display = "block";
        return;
        }

const lines = [
  `Score: ${data.feasibility_score}/100 (${data.status || "—"})`,
  data.monthly_payment !== undefined
    ? `Mensualité (estimée): ${Math.round(data.monthly_payment * 100) / 100} €`
    : "",
  data.total_budget !== undefined
    ? `Budget total (frais inclus estimés): ${Math.round(data.total_budget)} €`
    : "",
  data.current_interest_rate !== undefined
    ? `Taux utilisé: ${(data.current_interest_rate * 100).toFixed(2)}%`
    : "",
  Array.isArray(data.recommendations) && data.recommendations.length
    ? `Recommandations: ${data.recommendations.join(" | ")}`
    : "",
  data.application_id ? `Application ID: ${data.application_id}` : "",
  data.application_id ? `PDF (si payé): /api/dossier/${data.application_id}/pdf` : ""
].filter(Boolean);


      result.textContent = lines.join("\n");
      result.style.display = "block";
      window.scrollTo({top: document.body.scrollHeight, behavior: "smooth"});
    } catch(err) {
      result.textContent = "Erreur: " + (err?.message || err);
      result.style.display = "block";
    }
  });

  $("#show-rates").addEventListener("click", async () => {
    rates.style.display = "none";
    try {
      const resp = await fetch("/api/taux-actuels");
      const data = await resp.json();
      const src = data.source || data.rate_source || "—";
      const dt = data.date_maj || data.rate_last_update || "—";
      const taux = data.taux || data.rates || data;
      rates.textContent =
        "Taux: " + JSON.stringify(taux, null, 2) +
        "\nSource: " + src +
        "\nDernière mise à jour: " + dt;
      rates.style.display = "block";
    } catch(err) {
      rates.textContent = "Erreur: " + (err?.message || err);
      rates.style.display = "block";
    }
  });
})();
