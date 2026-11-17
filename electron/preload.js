const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
  confirmWrite: (payload) => ipcRenderer.invoke('confirm-write', payload),
  openDashboard: () => ipcRenderer.send('open-dashboard'),
  toggleMiniPet: () => ipcRenderer.send('toggle-minipet'),
  beginPetDrag: () => ipcRenderer.send('begin-pet-drag'),
  endPetDrag: () => ipcRenderer.send('end-pet-drag'),
  nudgePet: (delta) => ipcRenderer.send('nudge-pet', delta),
  hideMiniPet: () => ipcRenderer.send('hide-minipet'),
  setPetIgnoreMouse: (ignore) => ipcRenderer.send('pet-ignore-mouse', Boolean(ignore)),
  updateTrayStatus: (status) => ipcRenderer.send('tray-update', status),
});
