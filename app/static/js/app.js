(() => {
  const apiBase = window.FACEFORM?.apiBase || "/api/v1";
  const tokenKey = "faceform_access_token";
  const guestKey = "faceform_guest_token";

  function getToken() {
    return localStorage.getItem(tokenKey);
  }

  function setToken(token) {
    localStorage.setItem(tokenKey, token);
  }

  function clearToken() {
    localStorage.removeItem(tokenKey);
  }

  function getGuestToken() {
    return sessionStorage.getItem(guestKey);
  }

  function setGuestToken(token) {
    if (token) sessionStorage.setItem(guestKey, token);
  }

  function clearGuestToken() {
    sessionStorage.removeItem(guestKey);
  }

  async function api(path, options = {}) {
    const headers = new Headers(options.headers || {});
    const token = getToken();
    if (token) headers.set("Authorization", `Bearer ${token}`);
    if (options.body && !(options.body instanceof FormData)) headers.set("Content-Type", "application/json");
    const response = await fetch(`${apiBase}${path}`, { ...options, headers });
    if (response.status === 401 && token) {
      clearToken();
      if (location.pathname !== "/login" && location.pathname !== "/register") {
        location.href = `/login?next=${encodeURIComponent(location.pathname)}`;
      }
    }
    if (response.status === 204) return null;
    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = typeof body.detail === "string" ? body.detail : "Something went wrong. Please try again.";
      throw new Error(detail);
    }
    return body;
  }

  function toast(message, kind = "info") {
    const region = document.getElementById("toast-region");
    if (!region) return;
    const item = document.createElement("div");
    item.className = `toast ${kind}`;
    item.textContent = message;
    region.append(item);
    window.setTimeout(() => item.remove(), 4800);
  }

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, (character) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    })[character]);
  }

  function formatDate(value) {
    return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", year: "numeric" }).format(new Date(value));
  }

  function money(amount) {
    return new Intl.NumberFormat("en-KE", { style: "currency", currency: "KES", maximumFractionDigits: 0 }).format(amount);
  }

  function setBusy(button, busy, label) {
    if (!button) return;
    if (busy) {
      button.dataset.originalLabel = button.innerHTML;
      button.disabled = true;
      button.textContent = label;
    } else {
      button.disabled = false;
      if (button.dataset.originalLabel) button.innerHTML = button.dataset.originalLabel;
    }
  }

  async function downloadImage(imageId, title) {
    const token = getToken();
    if (!token) {
      location.href = `/login?next=${encodeURIComponent(location.pathname)}`;
      return;
    }
    try {
      const response = await fetch(`${apiBase}/images/${encodeURIComponent(imageId)}/download`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(body.detail || "Could not download this face.");
      }
      const blob = await response.blob();
      const objectUrl = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = objectUrl;
      link.download = `${String(title || "face").replace(/[<>:"/\\|?*\x00-\x1f]/g, "-")}.png`;
      document.body.append(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(objectUrl);
    } catch (error) {
      toast(`Download could not start: ${error.message}`, "error");
    }
  }

  function requireAuth() {
    if (getToken()) return true;
    location.href = `/login?next=${encodeURIComponent(location.pathname)}`;
    return false;
  }

  function mountMenu() {
    const toggle = document.querySelector(".menu-toggle");
    const nav = document.querySelector(".marketing-nav");
    if (toggle && nav) {
      toggle.addEventListener("click", () => {
        const isOpen = nav.classList.toggle("open");
        toggle.setAttribute("aria-expanded", String(isOpen));
      });
    }
    const sidebarToggle = document.querySelector(".sidebar-toggle");
    const sidebar = document.getElementById("sidebar");
    if (sidebarToggle && sidebar) {
      sidebarToggle.addEventListener("click", () => sidebar.classList.toggle("open"));
      document.addEventListener("click", (event) => {
        if (sidebar.classList.contains("open") && !sidebar.contains(event.target) && !sidebarToggle.contains(event.target)) {
          sidebar.classList.remove("open");
        }
      });
    }
    document.querySelectorAll("[data-logout]").forEach((button) => {
      button.addEventListener("click", () => {
        clearToken();
        location.href = "/";
      });
    });
  }

  function mountStudio() {
    const form = document.getElementById("generation-form");
    if (!form) return;
    const steps = [...form.querySelectorAll("[data-form-step]")];
    const indicators = [...document.querySelectorAll("[data-step-indicator]")];
    const description = form.elements.description;
    const countLabel = document.getElementById("description-count");
    const imageCount = form.elements.number_of_images;
    const cost = document.getElementById("review-cost");
    const creditLabel = document.getElementById("studio-credit-count");
    let creditsPerImage = 6;

    if (getToken()) {
      api("/auth/me").then((user) => {
        const userLink = document.querySelector(".app-top-links .user-link");
        if (userLink) {
          userLink.textContent = user.name.split(" ")[0];
          userLink.href = "/dashboard";
        }
        return api("/dashboard");
      }).then((summary) => {
        creditsPerImage = summary.credits_per_image;
        creditLabel.textContent = creditsPerImage;
        cost.textContent = creditsPerImage * Number(imageCount.value);
      }).catch(() => {});
    }

    const updateCost = () => { cost.textContent = creditsPerImage * Number(imageCount.value); };
    imageCount.addEventListener("change", updateCost);
    description.addEventListener("input", () => { countLabel.textContent = `${description.value.length} / 2000`; });

    function showStep(number) {
      steps.forEach((step) => step.classList.toggle("active", Number(step.dataset.formStep) === number));
      indicators.forEach((indicator) => {
        const stepNumber = Number(indicator.dataset.stepIndicator);
        indicator.classList.toggle("active", stepNumber === number);
        indicator.classList.toggle("complete", stepNumber < number);
      });
      if (number === 3) {
        document.getElementById("review-title").textContent = form.elements.title.value;
        document.getElementById("review-summary").textContent =
          `${form.elements.gender.value}, ${form.elements.age_range.value} · ${form.elements.ethnicity.value}. ${description.value}`;
        updateCost();
      }
    }

    form.querySelectorAll("[data-next-step]").forEach((button) => {
      button.addEventListener("click", () => {
        const current = Number(button.closest(".form-step").dataset.formStep);
        const fields = [...button.closest(".form-step").querySelectorAll("input, select, textarea")];
        const invalid = fields.find((field) => !field.reportValidity());
        if (invalid) return;
        showStep(Number(button.dataset.nextStep));
      });
    });
    form.querySelectorAll("[data-prev-step]").forEach((button) => {
      button.addEventListener("click", () => showStep(Number(button.dataset.prevStep)));
    });

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const submit = document.getElementById("generate-submit");
      const total = Number(imageCount.value) * creditsPerImage;
      if (!getToken() && Number(imageCount.value) > 1) {
        toast("Sign in to create more than one face at a time.", "error");
        return;
      }
      if (getToken()) {
        try {
          const dashboard = await api("/dashboard");
          if (dashboard.credits < total) {
            toast(`You need ${total} credits. Add credits to keep creating.`, "error");
            return;
          }
        } catch (error) {
          toast(error.message, "error");
          return;
        }
      }
      setBusy(submit, true, "Creating your face…");
      try {
        const payload = {
          title: form.elements.title.value.trim(),
          gender: form.elements.gender.value,
          age_range: form.elements.age_range.value,
          ethnicity: form.elements.ethnicity.value,
          description: description.value.trim(),
          number_of_images: Number(imageCount.value),
        };
        const headers = {};
        if (!getToken() && getGuestToken()) headers["X-Guest-Token"] = getGuestToken();
        const result = await api("/generations", { method: "POST", headers, body: JSON.stringify(payload) });
        if (result.guest_token) setGuestToken(result.guest_token);
        displayResults(result);
        toast("Your new character is ready.", "success");
        document.getElementById("generation-results").scrollIntoView({ behavior: "smooth", block: "start" });
      } catch (error) {
        toast(error.message, "error");
      } finally {
        setBusy(submit, false);
      }
    });
  }

  function displayResults(result) {
    const section = document.getElementById("generation-results");
    const grid = document.getElementById("result-grid");
    section.hidden = false;
    grid.replaceChildren();
    result.generation.images.forEach((image) => {
      const card = document.createElement("article");
      card.className = "result-card";
      const img = document.createElement("img");
      img.src = image.url;
      img.alt = image.title;
      img.loading = "lazy";
      const info = document.createElement("div");
      info.className = "result-card-info";
      const title = document.createElement("strong");
      title.textContent = image.title;
      info.append(title);
      if (getToken()) {
        const download = document.createElement("a");
        download.href = image.url;
        download.download = `${image.title}.png`;
        download.textContent = "Download";
        download.addEventListener("click", (event) => {
          event.preventDefault();
          downloadImage(image.id, image.title);
        });
        info.append(download);
      } else {
        const locked = document.createElement("span");
        locked.textContent = "Sign in to save";
        info.append(locked);
      }
      card.append(img, info);
      grid.append(card);
    });
    const saveBanner = document.getElementById("guest-save-banner");
    saveBanner.hidden = Boolean(getToken());
    if (!getToken()) {
      saveBanner.querySelector("a").href = "/register";
      sessionStorage.setItem("faceform_return_after_auth", "/gallery");
    }
  }

  async function mountDashboard() {
    if (!document.getElementById("welcome-name")) return;
    if (!requireAuth()) return;
    try {
      const [user, data, generations] = await Promise.all([
        api("/auth/me"), api("/dashboard"), api("/generations?limit=8"),
      ]);
      document.getElementById("welcome-name").textContent = user.name.split(" ")[0];
      document.getElementById("topbar-credits").textContent = data.credits;
      document.getElementById("stat-credits").textContent = data.credits;
      document.getElementById("stat-images").textContent = data.images_count;
      document.getElementById("stat-albums").textContent = data.albums_count;
      const gallery = document.getElementById("dashboard-gallery");
      const images = generations.flatMap((generation) => generation.images).slice(0, 4);
      gallery.innerHTML = images.length ? images.map((image) => `
        <a class="mini-image-card" href="/gallery">
          <img src="${escapeHtml(image.url)}" alt="${escapeHtml(image.title)}" loading="lazy">
          <div><strong>${escapeHtml(image.title)}</strong><span>${formatDate(image.created_at)}</span></div>
        </a>`).join("") : `<div class="empty-state"><span class="empty-symbol">✧</span><strong>Your gallery is a blank canvas.</strong><p>Create your first original character and it'll show up here.</p><a class="button button-primary" href="/product">Create a face <span>→</span></a></div>`;
      const transactions = document.getElementById("transaction-list");
      transactions.innerHTML = data.recent_transactions.length
        ? data.recent_transactions.map((item) => `
          <div class="transaction-row"><div><span class="transaction-description">${escapeHtml(item.description)}</span><span class="transaction-date">${formatDate(item.created_at)}</span></div><span></span><strong class="transaction-amount ${item.credits > 0 ? "positive" : "negative"}">${item.credits > 0 ? "+" : ""}${item.credits} credits</strong></div>`).join("")
        : `<div class="empty-state"><strong>No activity just yet.</strong><p>Your creations and purchases will show up here.</p></div>`;
    } catch (error) {
      toast(error.message, "error");
    }
  }

  async function mountGallery() {
    const grid = document.getElementById("gallery-grid");
    if (!grid) return;
    if (!requireAuth()) return;
    const albumsContainer = document.getElementById("album-list");
    let images = [];
    let albums = [];
    let activeAlbum = "";

    const loadImages = async () => {
      const query = activeAlbum ? `?album_id=${encodeURIComponent(activeAlbum)}` : "";
      images = await api(`/gallery${query}`);
      renderImages();
    };

    const renderImages = () => {
      const search = document.getElementById("gallery-search").value.toLowerCase().trim();
      const sort = document.getElementById("gallery-sort").value;
      const matching = images.filter((image) => image.title.toLowerCase().includes(search));
      if (sort === "oldest") matching.sort((a, b) => new Date(a.created_at) - new Date(b.created_at));
      if (sort === "newest") matching.sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
      if (sort === "name") matching.sort((a, b) => a.title.localeCompare(b.title));
      grid.innerHTML = matching.length ? matching.map((image) => `
        <article class="gallery-card" data-image-id="${escapeHtml(image.id)}">
          <div class="gallery-image-wrap"><img src="${escapeHtml(image.url)}" alt="${escapeHtml(image.title)}" loading="lazy"></div>
          <div class="gallery-card-body"><div class="gallery-card-title"><strong title="${escapeHtml(image.title)}">${escapeHtml(image.title)}</strong></div>
            <p class="gallery-card-date">${formatDate(image.created_at)}</p>
            <div class="gallery-card-actions">
              <a href="${window.FACEFORM.apiBase}/images/${encodeURIComponent(image.id)}/download" data-download="${escapeHtml(image.id)}">Download</a>
              <button type="button" data-rename="${escapeHtml(image.id)}">Edit</button>
              <button type="button" data-assign="${escapeHtml(image.id)}" aria-label="Add to album">Album</button>
              <button class="danger-action" type="button" data-delete-image="${escapeHtml(image.id)}" aria-label="Delete face">×</button>
            </div>
          </div>
        </article>`).join("") : `<div class="empty-state"><span class="empty-symbol">✧</span><strong>${search ? "No faces found." : activeAlbum ? "This album is ready for faces." : "Your gallery is a blank canvas."}</strong><p>${search ? "Try another search, or clear the search box." : "Create your first original character and collect it here."}</p>${!activeAlbum && !search ? '<a class="button button-primary" href="/product">Create a face <span>→</span></a>' : ""}</div>`;
    };

    const renderAlbums = () => {
      albumsContainer.innerHTML = `<button type="button" class="album-chip ${activeAlbum ? "" : "active"}" data-album-filter=""><span class="album-symbol">▦</span><span><strong>All faces</strong><small>${images.length} total</small></span></button>` +
        albums.map((album) => `<div class="album-chip ${activeAlbum === album.id ? "active" : ""}" data-album-id="${escapeHtml(album.id)}">
          <button type="button" class="album-filter-button" data-album-filter="${escapeHtml(album.id)}"><span class="album-symbol">▤</span><span><strong>${escapeHtml(album.title)}</strong><small>${album.image_count} ${album.image_count === 1 ? "face" : "faces"}</small></span></button>
          <button type="button" class="album-menu" data-edit-album="${escapeHtml(album.id)}" aria-label="Edit album">···</button>
        </div>`).join("");
    };

    try {
      [albums] = await Promise.all([api("/albums")]);
      await loadImages();
      const credits = await api("/dashboard");
      document.getElementById("topbar-credits").textContent = credits.credits;
      renderAlbums();
    } catch (error) {
      toast(error.message, "error");
    }

    document.getElementById("gallery-search").addEventListener("input", renderImages);
    document.getElementById("gallery-sort").addEventListener("change", renderImages);
    albumsContainer.addEventListener("click", async (event) => {
      const filter = event.target.closest("[data-album-filter]");
      if (filter) {
        activeAlbum = filter.dataset.albumFilter;
        document.getElementById("gallery-title").textContent = activeAlbum ? albums.find((album) => album.id === activeAlbum)?.title || "Album" : "All faces";
        try {
          await loadImages();
          renderAlbums();
        } catch (error) { toast(error.message, "error"); }
        return;
      }
      const edit = event.target.closest("[data-edit-album]");
      if (edit) openAlbumDialog(albums.find((album) => album.id === edit.dataset.editAlbum));
    });
    grid.addEventListener("click", async (event) => {
      const download = event.target.closest("[data-download]");
      if (download) {
        event.preventDefault();
        const image = images.find((item) => item.id === download.dataset.download);
        if (image) await downloadImage(image.id, image.title);
        return;
      }
      const rename = event.target.closest("[data-rename]");
      if (rename) {
        const image = images.find((item) => item.id === rename.dataset.rename);
        const title = window.prompt("Give this face a new name", image?.title || "");
        if (!title?.trim()) return;
        try {
          await api(`/images/${encodeURIComponent(image.id)}`, { method: "PATCH", body: JSON.stringify({ title: title.trim() }) });
          await loadImages();
          toast("Face name updated.", "success");
        } catch (error) { toast(error.message, "error"); }
        return;
      }
      const assign = event.target.closest("[data-assign]");
      if (assign) {
        if (!albums.length) {
          toast("Create an album first to organize this face.");
          return;
        }
        const choices = albums.map((album, index) => `${index + 1}. ${album.title}`).join("\n");
        const chosen = Number(window.prompt(`Add to which album? Enter a number:\n${choices}`));
        if (!Number.isInteger(chosen) || chosen < 1 || chosen > albums.length) return;
        try {
          await api(`/albums/${encodeURIComponent(albums[chosen - 1].id)}/images/${encodeURIComponent(assign.dataset.assign)}`, { method: "POST" });
          albums = await api("/albums");
          renderAlbums();
          toast("Face added to your album.", "success");
        } catch (error) { toast(error.message, "error"); }
        return;
      }
      const remove = event.target.closest("[data-delete-image]");
      if (remove && window.confirm("Delete this face from your gallery?")) {
        try {
          await api(`/images/${encodeURIComponent(remove.dataset.deleteImage)}`, { method: "DELETE" });
          await loadImages();
          albums = await api("/albums");
          renderAlbums();
          toast("Face deleted.", "success");
        } catch (error) { toast(error.message, "error"); }
      }
    });

    document.querySelectorAll("[data-create-album]").forEach((button) => button.addEventListener("click", () => openAlbumDialog()));
    const albumForm = document.getElementById("album-form");
    albumForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const data = new FormData(albumForm);
      const id = data.get("album_id");
      const payload = { title: data.get("title").trim(), description: data.get("description").trim() };
      try {
        await api(id ? `/albums/${encodeURIComponent(id)}` : "/albums", {
          method: id ? "PATCH" : "POST",
          body: JSON.stringify(payload),
        });
        document.getElementById("album-modal").close();
        albums = await api("/albums");
        renderAlbums();
        toast(id ? "Album updated." : "Album created.", "success");
      } catch (error) { toast(error.message, "error"); }
    });
  }

  function openAlbumDialog(album = null) {
    const dialog = document.getElementById("album-modal");
    const form = document.getElementById("album-form");
    if (!dialog || !form) return;
    form.elements.album_id.value = album?.id || "";
    form.elements.title.value = album?.title || "";
    form.elements.description.value = album?.description || "";
    document.getElementById("album-modal-title").textContent = album ? "Edit album" : "New album";
    let deleteButton = document.getElementById("delete-album");
    if (deleteButton) deleteButton.remove();
    if (album) {
      deleteButton = document.createElement("button");
      deleteButton.type = "button";
      deleteButton.id = "delete-album";
      deleteButton.className = "text-button";
      deleteButton.textContent = "Delete album";
      deleteButton.addEventListener("click", async () => {
        if (!window.confirm(`Delete "${album.title}"? Your faces won't be deleted.`)) return;
        try {
          await api(`/albums/${encodeURIComponent(album.id)}`, { method: "DELETE" });
          dialog.close();
          window.location.reload();
        } catch (error) { toast(error.message, "error"); }
      });
      form.querySelector(".modal-actions").prepend(deleteButton);
    }
    dialog.showModal();
  }

  async function mountBilling() {
    const pricing = document.getElementById("pricing-grid");
    if (!pricing) return;
    if (!requireAuth()) return;
    try {
      const [packs, dashboard, payments] = await Promise.all([
        api("/billing/packs"), api("/dashboard"), api("/billing/payments"),
      ]);
      document.getElementById("topbar-credits").textContent = dashboard.credits;
      document.getElementById("billing-balance").textContent = dashboard.credits;
      document.getElementById("billing-cost").textContent = dashboard.credits_per_image;
      pricing.innerHTML = packs.map((pack, index) => `
        <article class="price-card ${index === 1 ? "featured" : ""}">
          ${index === 1 ? '<span class="popular-tag">Creator favourite</span>' : ""}
          <span>${escapeHtml(pack.code.charAt(0).toUpperCase() + pack.code.slice(1))}</span>
          <strong class="price-amount">${money(pack.amount_kes)} <small>one time</small></strong>
          <p class="pack-credits"><strong>${pack.credits} credits</strong> · ${Math.floor(pack.credits / dashboard.credits_per_image)} faces</p>
          <p class="pack-value">Your credits never expire.</p>
          <button class="button ${index === 1 ? "button-primary" : "button-outline"}" type="button" data-buy-pack="${escapeHtml(pack.code)}">Choose this pack <span>→</span></button>
        </article>`).join("");
      renderPayments(payments);
      pricing.addEventListener("click", (event) => {
        const button = event.target.closest("[data-buy-pack]");
        const pack = packs.find((item) => item.code === button?.dataset.buyPack);
        if (pack) openPaymentDialog(pack);
      });
    } catch (error) { toast(error.message, "error"); }

    document.querySelector("[data-close-payment]").addEventListener("click", () => document.getElementById("payment-modal").close());
    const methodSelect = document.getElementById("payment-method");
    methodSelect.addEventListener("change", () => {
      document.getElementById("phone-field").classList.toggle("hidden", methodSelect.value !== "mpesa_stk");
    });
    methodSelect.dispatchEvent(new Event("change"));
    document.getElementById("payment-form").addEventListener("submit", async (event) => {
      event.preventDefault();
      const form = event.currentTarget;
      const button = document.getElementById("payment-submit");
      const payload = {
        pack_code: form.elements.pack_code.value,
        method: form.elements.method.value,
      };
      if (payload.method === "mpesa_stk") payload.phone_number = form.elements.phone_number.value.trim();
      setBusy(button, true, "Connecting securely…");
      try {
        const result = await api("/billing/payments", { method: "POST", body: JSON.stringify(payload) });
        const info = result.instructions || {};
        if (info.checkout_url) {
          window.location.href = info.checkout_url;
          return;
        }
        renderPaymentInstructions(result.payment, info);
        if (payload.method !== "mpesa_stk") {
          const payments = await api("/billing/payments");
          renderPayments(payments);
        }
        toast("Payment started. Your credits appear after confirmation.", "success");
      } catch (error) {
        toast(error.message, "error");
      } finally {
        setBusy(button, false);
      }
    });
  }

  function renderPayments(payments) {
    const list = document.getElementById("payment-list");
    if (!list) return;
    list.innerHTML = payments.length ? payments.map((payment) => `
      <div class="payment-row">
        <div><span class="payment-method-name">${escapeHtml(payment.method.replaceAll("_", " ").replace("mpesa", "M-Pesa").replace(/\b\w/g, (letter) => letter.toUpperCase()))} · ${payment.credits} credits</span><span class="transaction-date">${formatDate(payment.created_at)}${payment.receipt_number ? ` · ${escapeHtml(payment.receipt_number)}` : ""}</span></div>
        <span class="payment-status ${escapeHtml(payment.status)}">${escapeHtml(payment.status)}</span>
        <strong class="transaction-amount">${money(payment.amount_kes)}</strong>
      </div>`).join("") : `<div class="empty-state"><strong>No payments yet.</strong><p>Your credit pack purchases will show here.</p></div>`;
  }

  function openPaymentDialog(pack) {
    const dialog = document.getElementById("payment-modal");
    const form = document.getElementById("payment-form");
    form.elements.pack_code.value = pack.code;
    form.elements.phone_number.value = "";
    document.getElementById("payment-order").innerHTML =
      `<span>${escapeHtml(pack.credits)} credits · ${escapeHtml(pack.code.charAt(0).toUpperCase() + pack.code.slice(1))}</span><strong>${money(pack.amount_kes)}</strong>`;
    const instructions = document.getElementById("payment-instructions");
    instructions.replaceChildren();
    instructions.hidden = true;
    document.getElementById("payment-submit").hidden = false;
    document.getElementById("payment-method").dispatchEvent(new Event("change"));
    dialog.showModal();
  }

  function renderPaymentInstructions(payment, details) {
    const container = document.getElementById("payment-instructions");
    container.replaceChildren();
    container.hidden = false;
    const message = document.createElement("p");
    if (payment.method === "mpesa_stk") {
      message.textContent = details.message || "Approve the payment request on your phone. Your credits will appear once M-Pesa confirms it.";
      container.append(message);
      if (details.checkout_request_id) {
        const reference = document.createElement("span");
        reference.className = "instructions-reference";
        reference.textContent = `Request: ${details.checkout_request_id}`;
        container.append(reference);
      }
    } else {
      message.textContent = payment.method === "mpesa_qr"
        ? `Scan this QR code using M-Pesa, then pay ${money(payment.amount_kes)}. Your credits are added after payment confirmation.`
        : `Open M-Pesa and select ${details.payment_method}. Pay ${money(payment.amount_kes)} to business number ${details.business_number}.`;
      container.append(message);
      if (details.qr_code) {
        const image = document.createElement("img");
        image.src = details.qr_code;
        image.alt = "M-Pesa payment QR code";
        container.append(image);
      }
      if (details.account_reference) {
        const reference = document.createElement("span");
        reference.className = "instructions-reference";
        reference.textContent = `Account reference: ${details.account_reference}`;
        container.append(reference);
      }
    }
    const statusButton = document.createElement("button");
    statusButton.className = "button button-outline button-small";
    statusButton.type = "button";
    statusButton.textContent = "Check payment status";
    statusButton.style.marginTop = "12px";
    statusButton.addEventListener("click", async () => {
      try {
        const latest = await api(`/billing/payments/${encodeURIComponent(payment.id)}`);
        if (latest.status === "paid") {
          toast("Payment confirmed. Your credits are ready.", "success");
          document.getElementById("payment-modal").close();
          window.location.reload();
        } else {
          toast(latest.status === "failed" ? "This payment did not go through." : "Still waiting for payment confirmation.");
        }
      } catch (error) { toast(error.message, "error"); }
    });
    container.append(statusButton);
  }

  window.Faceform = {
    api,
    clearGuestToken,
    clearToken,
    escapeHtml,
    getGuestToken,
    getToken,
    money,
    mountDashboard,
    setGuestToken,
    setToken,
    toast,
  };

  document.addEventListener("DOMContentLoaded", () => {
    mountMenu();
    mountStudio();
    mountDashboard();
    mountGallery();
    mountBilling();
  });
})();
