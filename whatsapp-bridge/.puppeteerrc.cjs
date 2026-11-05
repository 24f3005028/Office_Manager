// This local Windows workflow uses installed Chrome (or an explicit executable).
// Avoid browser archive downloads and their extract-zip dependency during install.
module.exports = { skipDownload: true };
