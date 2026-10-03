<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Alert, Avatar, Badge, Button, FrappeUIProvider, LoadingText, Switch, TextInput, useCall, toast } from 'frappe-ui'

// Bump on every shipped change set - see apps/soypaq/CHANGELOG.md
const APP_VERSION = '0.12.0'
const APP_BUILD_DATE = '2026-10-03'

const screen = ref('home')
const history = ref([])
const scanValue = ref('1Z-MVP-0001')
const searchValue = ref('')
const scanMode = ref('barcode')
const myTasksTab = ref('open')
const myTasksDrawerTask = ref(null)
const myTasksDrawerItems = ref([])
const myTasksDrawerSource = ref(null)
const myTasksDrawerIntegrity = ref(null)
const myTasksDrawerCreated = ref('')
const myTasksDrawerClaimedAt = ref('')
const myTasksDrawerActivity = ref([])
const myTasksDrawerItemsLoading = ref(false)
const myTasksClaimLoading = ref(false)
const inventoryQuery = ref('')
// Inventory filters: Company (tenant that holds the stock), Color, Size. Collapsed by default.
const traitFilter = ref({ company: '', color: '', size: '' })
const filtersOpen = ref(false)
const FILTER_LABELS = { company: 'Company', color: 'Color', size: 'Size' }
const activeFilterCount = computed(() => Object.values(traitFilter.value).filter(Boolean).length)
const SIZE_ORDER = ['XXS', 'XS', 'S', 'M', 'L', 'XL', 'XXL', 'XXXL']
const traitOptions = computed(() => {
  const pick = (key) => [...new Set(inventory.value.items.map((item) => item[key]).filter(Boolean))]
  return {
    company: pick('company').sort(),
    color: pick('color').sort(),
    size: pick('size').sort((a, b) => (SIZE_ORDER.indexOf(a) + 1 || 99) - (SIZE_ORDER.indexOf(b) + 1 || 99)),
  }
})
const itemTraits = (code) => inventory.value.items.find((item) => item.item_code === code) || {}
const traitMatch = (item) => Object.entries(traitFilter.value).every(([key, value]) => !value || key === 'company' && !item.company || item[key] === value)
const inventoryView = ref('staged')
const globalActivity = ref([])
const globalActivityLoading = ref(false)
const inventoryFilter = ref('all')
const selectedItemCode = ref('')
const pickScanValue = ref('')
const selectedPickSku = ref('')
const selectedPickTaskName = ref('')
const selectedPackTaskName = ref('')
const packMode = ref('tasks')
const pickMode = ref('tasks')
const pickActionLoading = ref(false)
const pickIssueReason = ref('Barcode Issue')
const vibration = ref(true)
const sound = ref(true)
const lastDemoSync = ref('Just now')
const packScanValue = ref('')
const scannerOpen = ref(false)
const scannerTarget = ref('sku')
const scannerStarting = ref(false)
const pickActionTag = ref('')
const receiveMode = ref('tasks')
const selectedPackageName = ref('')
const receiveScanValue = ref('')
const selectedReceiveSku = ref('')
const stagingBinInputs = ref({})
const stagingTargetSku = ref('')
const shipMode = ref('tasks')
const selectedShipmentTaskName = ref('')
const createFormOpen = ref(false)
const createFormType = ref('')
const createCustomer = ref('')
const createWarehouse = ref('')
const createPackageType = ref('Carton Box')
const createCarrier = ref('UPS')
const createItems = ref([{ item_code: '', quantity: 1 }])
// Scan-first pick builder (Pick screen "New Pick Task"). One line per item; a line's bin decides
// which Pick Task it lands in (one task per bin, created server-side in a single call).
const builderOpen = ref(false)
const builderScan = ref('')
const builderLines = ref([])
const builderBin = ref(null)
const builderEditKey = ref('')
const builderBusy = ref(false)
const builderFlashKey = ref('')
const builderInput = ref(null)
const builderNames = ref([])
let scannerHandler = null

const bootstrap = useCall({
  url: '/api/v2/method/soypaq.api.get_mobile_bootstrap',
  params: () => ({
    pick_task_name: selectedPickTaskName.value,
    pack_task_name: selectedPackTaskName.value,
    shipment_task_name: selectedShipmentTaskName.value,
    package_name: selectedPackageName.value,
  }),
  onError: (error) => toast.error(error.message || 'Unable to load WMS data'),
})
const scanner = useCall({ url: '/api/v2/method/soypaq.api.scan', immediate: false })
const confirmPickLocationRequest = useCall({ url: '/api/v2/method/soypaq.api.confirm_pick_location', immediate: false })
const pickItemRequest = useCall({ url: '/api/v2/method/soypaq.api.pick_item', immediate: false })
const unpickItemRequest = useCall({ url: '/api/v2/method/soypaq.api.unpick_item', immediate: false })
const pickAllRequest = useCall({ url: '/api/v2/method/soypaq.api.pick_all', immediate: false })
const flagPickItemRequest = useCall({ url: '/api/v2/method/soypaq.api.flag_pick_item', immediate: false })
const completePickRequest = useCall({ url: '/api/v2/method/soypaq.api.complete_pick', immediate: false })
const packItemRequest = useCall({ url: '/api/v2/method/soypaq.api.pack_item', method: 'POST', immediate: false })
const packAllRequest = useCall({ url: '/api/v2/method/soypaq.api.pack_all', method: 'POST', immediate: false })
const unpackItemRequest = useCall({ url: '/api/v2/method/soypaq.api.unpack_item', method: 'POST', immediate: false })
const completePackRequest = useCall({ url: '/api/v2/method/soypaq.api.complete_pack', method: 'POST', immediate: false })
const emptyInventory = { items: [], locations: [], summary: { sku_count: 0, on_hand: 0, reserved: 0, available: 0, assigned: 0, location_count: 0 } }
const fallback = {
  operator: { id: '', name: 'Warehouse Operator', role: 'Warehouse Operator' },
  stats: { receive: 0, pick: 0, pack: 0, ship: 0, exceptions: 0 },
  tasks: [], my_tasks: { open: [], active: [], history: [] },
  receive: { asn: {}, package: { items: [] }, packages: [] }, pick: { items: [], tasks: [], context: {} }, pack: { items: [], tasks: [], context: {} },
  ship: { items: [], tasks: [], chain: {}, status: '', carrier: '', tracking_number: '', label_url: '', name: '', route: '' },
  issues: [], inventory: emptyInventory, sync: { status: 'Connecting', pending: 0, last_sync: 'Loading' },
}

const data = computed(() => bootstrap.data || fallback)
const inventory = computed(() => data.value.inventory || emptyInventory)
const title = computed(() => ({
  home: 'Welcome back', tasks: 'My Tasks', search: 'Manual Search', exceptions: 'Exceptions Queue',
  receive: 'Receive Orders', pick: 'Pick Orders', pack: 'Pack Orders', ship: 'Ship Orders', returns: 'Returns',
  inventory: 'Live Inventory', settings: 'Settings', sync: 'Sync Status',
})[screen.value] || 'SoyPaq WMS')
const currentTask = computed(() => data.value.tasks.find((task) => task.kind.toLowerCase() === screen.value) || null)
function filterMyTasks(list) {
  const query = searchValue.value.trim().toLowerCase()
  if (!query) return list
  return list.filter((t) => `${t.reference} ${t.customer} ${t.kind}`.toLowerCase().includes(query))
}
const myTasksScreenKind = computed(() => {
  if (screen.value === 'pick' && pickMode.value === 'tasks') return 'Pick'
  if (screen.value === 'pack' && packMode.value === 'tasks') return 'Pack'
  if (screen.value === 'ship' && shipMode.value === 'tasks') return 'Ship'
  if (screen.value === 'receive' && receiveMode.value === 'tasks') return 'Receive'
  return null
})
const showMyTasksList = computed(() => screen.value === 'tasks' || myTasksScreenKind.value !== null)
function filterByScreenKind(list) {
  return myTasksScreenKind.value ? list.filter((t) => t.kind === myTasksScreenKind.value) : list
}
const myTasksOpen = computed(() => filterByScreenKind(filterMyTasks(data.value.my_tasks?.open || [])))
const myTasksActive = computed(() => filterByScreenKind(filterMyTasks(data.value.my_tasks?.active || [])))
const myTasksHistory = computed(() => filterByScreenKind(filterMyTasks(data.value.my_tasks?.history || [])))
const myTasksCurrentList = computed(() => ({ open: myTasksOpen.value, active: myTasksActive.value, history: myTasksHistory.value }[myTasksTab.value]))
const MY_TASKS_CREATE_LABEL = {
  Pick: 'New Pick Task (no order needed)',
  Pack: 'New Pack Task (no Pick Task needed)',
  Ship: 'New Shipment Task (no Pack Task needed)',
}
const myTasksClaimedByMe = computed(() => myTasksDrawerTask.value?.assigned_to?.id && myTasksDrawerTask.value.assigned_to.id === data.value.operator.id)
const myTasksClaimedByOther = computed(() => myTasksDrawerTask.value?.assigned_to?.id && myTasksDrawerTask.value.assigned_to.id !== data.value.operator.id)
const MY_TASKS_DONE_STATUS = { Pick: ['Completed'], Pack: ['Completed'], Ship: ['Shipped'], Receive: ['Stored', 'Consolidated', 'Shipped', 'Delivered'] }
const PICK_ACTION_DESCRIPTIONS = {
  Picked: 'Scanned and picked',
  Unpicked: 'Removed from the pick',
  Handpicked: 'Entered manually - no barcode scan',
  Exception: 'Flagged as an exception',
  Completed: 'Pick task finished',
}
const myTasksDrawerIsDone = computed(() => {
  const task = myTasksDrawerTask.value
  return task ? (MY_TASKS_DONE_STATUS[task.kind] || []).includes(task.status) : false
})
const filteredInventory = computed(() => inventory.value.items.filter((item) => {
  const query = inventoryQuery.value.trim().toLowerCase()
  const queryMatch = !query || `${item.item_code} ${item.item_name} ${item.item_group} ${item.color} ${item.size} ${item.collection} ${item.primary_location}`.toLowerCase().includes(query)
  if (!traitMatch(item)) return false
  const filterMatch = inventoryFilter.value === 'all'
    || (inventoryFilter.value === 'stock' && item.on_hand > 0)
    || (inventoryFilter.value === 'reserved' && item.reserved > 0)
    || (inventoryFilter.value === 'unassigned' && !item.locations.length)
  return queryMatch && filterMatch
}))
const selectedInventoryItem = computed(() => inventory.value.items.find((item) => item.item_code === selectedItemCode.value) || null)
const receiveTotal = computed(() => data.value.receive.package.items.length)
const receiveDone = computed(() => data.value.receive.package.items.filter((item) => Number(item.received || 0) >= Number(item.quantity || 0) || item.status === 'Missing').length)
const receiveStatus = computed(() => data.value.receive.package.status || '')
const receiveStored = computed(() => ['Stored', 'Consolidated'].includes(receiveStatus.value))
const receiveConfirmed = computed(() => receiveTotal.value > 0 && receiveDone.value >= receiveTotal.value)
const receiveStageableRows = computed(() => data.value.receive.package.items.filter((item) => Number(item.received || 0) > 0 && item.status !== 'Missing' && !item.assigned_bin))
// Lines actually counted into this box (a blind package has nothing expected, so this is the whole list).
const receiveLines = computed(() => data.value.receive.package.items.filter((item) => Number(item.received || 0) > 0 && item.status !== 'Missing'))
const receiveUnits = computed(() => receiveLines.value.reduce((total, item) => total + Number(item.received || 0), 0))
const receiveStaged = computed(() => receiveConfirmed.value && receiveStageableRows.value.length === 0)
const selectedReceiveItem = computed(() => data.value.receive.package.items.find((item) => item.sku === selectedReceiveSku.value) || null)
const openTaskCount = computed(() => Number(data.value.stats.receive || 0) + Number(data.value.stats.pick || 0) + Number(data.value.stats.pack || 0) + Number(data.value.stats.ship || 0))
const hasNegativeStock = computed(() => inventory.value.items.some((item) => (item.locations || []).some((loc) => Number(loc.available) < 0)))
const shipChain = computed(() => data.value.ship.chain || {})
const stagedBins = computed(() => {
  const query = inventoryQuery.value.trim().toLowerCase()
  return (inventory.value.bins || []).filter((bin) => {
    if (!bin.on_hand) return false
    if (!query) return true
    return `${bin.name} ${bin.label}`.toLowerCase().includes(query)
      || bin.items.some((i) => `${i.item_code} ${i.item_name}`.toLowerCase().includes(query))
  }).filter((bin) => !traitFilter.value.company || bin.company === traitFilter.value.company)
    .filter((bin) => !traitFilter.value.color && !traitFilter.value.size
      || bin.items.some((i) => traitMatch({ ...itemTraits(i.item_code), company: '' })))
})
const shipTotal = computed(() => data.value.ship.items.reduce((total, item) => total + Number(item.quantity || 0), 0))
const shipPacked = computed(() => data.value.ship.items.reduce((total, item) => total + Number(item.packed || 0), 0))
const shipStatus = computed(() => data.value.ship.status || '')
const shipShipped = computed(() => shipStatus.value === 'Shipped')
const pickTotal = computed(() => data.value.pick.items.reduce((total, item) => total + Number(item.quantity || 0), 0))
const pickDone = computed(() => data.value.pick.items.reduce((total, item) => total + Number(item.picked || 0), 0))
const packTotal = computed(() => data.value.pack.items.reduce((total, item) => total + Number(item.quantity || 0), 0))
const packDone = computed(() => data.value.pack.items.reduce((total, item) => total + Number(item.packed || 0), 0))
const pickContext = computed(() => data.value.pick.context || {})
const packContext = computed(() => data.value.pack.context || {})
const pickLocationConfirmed = computed(() => Boolean(data.value.pick.location_confirmed))
const pickComplete = computed(() => data.value.pick.status === 'Completed')
const packComplete = computed(() => data.value.pack.status === 'Completed')
const pickTaskName = computed(() => data.value.pick.task?.name || '')
const packTaskName = computed(() => data.value.pack.task?.name || '')
const pickMutationLoading = computed(() => pickActionLoading.value || confirmPickLocationRequest.loading || pickItemRequest.loading || unpickItemRequest.loading || pickAllRequest.loading || flagPickItemRequest.loading || completePickRequest.loading)
const pickRows = computed(() => data.value.pick.items || [])
const activePickRows = computed(() => pickRows.value.filter((item) => Number(item.picked || 0) < Number(item.quantity || 0) && item.status !== 'Short'))
const selectedPickItem = computed(() => pickRows.value.find((item) => item.sku === selectedPickSku.value) || activePickRows.value[0] || pickRows.value[0] || null)
const pickBinGroups = computed(() => {
  const groups = new Map()
  for (const item of pickRows.value) {
    const bin = item.source_bin || item.source_warehouse || 'No bin assigned'
    if (!groups.has(bin)) groups.set(bin, [])
    groups.get(bin).push(item)
  }
  return Array.from(groups.entries()).map(([bin, items]) => ({ bin, items }))
})
const packMutationLoading = computed(() => packItemRequest.loading || packAllRequest.loading || unpackItemRequest.loading || completePackRequest.loading)

function formatQty(value) { return Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: 2 }) }
function formatCurrency(value) { return `$${Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: 0 })}` }
const homeSearchValue = ref('')
function formatDateTime(value) {
  if (!value) return ''
  const date = new Date(String(value).replace(' ', 'T'))
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleString([], { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })
}
// Live elapsed-time timer. Kept as a plain (start timestamp) -> (formatted string)
// function rather than baked into one screen, so it's a one-line reuse the next time
// this pattern lands on Receive/Pack/Ship (see PROJECT.md "Pick screen QoL").
const nowTick = ref(Date.now())
function formatElapsed(startValue) {
  if (!startValue) return ''
  const start = new Date(String(startValue).replace(' ', 'T')).getTime()
  if (Number.isNaN(start)) return ''
  const totalSeconds = Math.max(0, Math.floor((nowTick.value - start) / 1000))
  const h = Math.floor(totalSeconds / 3600)
  const m = Math.floor((totalSeconds % 3600) / 60)
  const s = totalSeconds % 60
  const pad = (n) => String(n).padStart(2, '0')
  return h > 0 ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`
}
function setScreen(next, remember = true) {
  if (next === screen.value) return
  if (remember) history.value.push(screen.value)
  screen.value = next
  selectedItemCode.value = ''
  if (next !== 'pick') pickMode.value = 'tasks'
  if (next !== 'pack') packMode.value = 'tasks'
  if (next !== 'receive') receiveMode.value = 'tasks'
  if (next !== 'ship') shipMode.value = 'tasks'
  window.scrollTo({ top: 0, behavior: 'smooth' })
  if (['receive', 'pick', 'pack', 'ship', 'inventory'].includes(next)) reloadQuietly()
}
function goBack() {
  screen.value = history.value.pop() || 'home'
  selectedItemCode.value = ''
  window.scrollTo({ top: 0, behavior: 'smooth' })
}
function goHome() {
  history.value = []
  screen.value = 'home'
  selectedItemCode.value = ''
  window.scrollTo({ top: 0, behavior: 'smooth' })
}
async function runScan() {
  try {
    const result = await scanner.submit({ code: scanValue.value })
    const match = result || scanner.data
    if (!match?.found) {
      toast.error(`No WMS record found for ${scanValue.value}`)
      setScreen('exceptions')
      return
    }
    if (match.doctype === 'Item') {
      inventoryQuery.value = match.name
      setScreen('inventory')
      selectedItemCode.value = match.name
    } else if (match.doctype === 'Warehouse') {
      inventoryQuery.value = match.name
      inventoryView.value = 'staged'
      setScreen('inventory')
    } else {
      const view = { 'Inbound ASN': 'receive', 'Inbound Package': 'receive', 'Pick Task': 'pick', 'Pack Task': 'pack', 'Shipment Task': 'ship' }[match.doctype]
      setScreen(view || 'tasks')
    }
    toast.success(`${match.doctype} found`)
  } catch (error) { toast.error(error.message || 'Scan failed') }
}
function openDesk(route) { route ? window.location.assign(route) : toast.info('No ERPNext record is linked yet') }
async function refresh(message = 'Live WMS data refreshed') {
  try {
    await bootstrap.reload()
    lastDemoSync.value = new Date().toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
    toast.success(message)
  } catch (error) { toast.error(error.message || 'Refresh failed') }
}
async function reloadQuietly() {
  if (document.hidden || bootstrap.loading || pickApiBusy) return
  try {
    await bootstrap.reload()
    lastDemoSync.value = new Date().toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
  } catch {
    // The explicit refresh action reports errors; background refresh stays quiet.
  }
}
async function mutate(request, params, message) {
  try {
    await request.submit(params)
    await bootstrap.reload()
    lastDemoSync.value = new Date().toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
    toast.success(message)
  } catch (error) {
    toast.error(error.message || 'The WMS update could not be saved')
  }
}
let pickApiBusy = false
function extractErrorMessage(payload, fallback) {
  // frappe.throw() puts the real user-facing text in _server_messages (a JSON-encoded
  // array of JSON-encoded {message} objects), not in payload.message - that key holds
  // the function's return value on success, so blindly reusing it on error surfaces the
  // generic HTTP status text ("EXPECTATION FAILED") instead of the actual error.
  if (payload?._server_messages) {
    try {
      const first = JSON.parse(JSON.parse(payload._server_messages)[0])
      if (first?.message) return first.message
    } catch { /* fall through to fallback */ }
  }
  return fallback
}
async function pickApi(method, params, message) {
  if (pickApiBusy) return null
  pickApiBusy = true
  pickActionLoading.value = true
  try {
    const body = new URLSearchParams()
    Object.entries(params).forEach(([key, value]) => body.append(key, value ?? ''))
    const csrfToken = window.csrf_token !== '{{ csrf_token }}' ? window.csrf_token : null
    const response = await window.fetch(`/api/method/soypaq.api.${method}`, {
      method: 'POST',
      cache: 'no-store',
      credentials: 'same-origin',
      headers: {
        Accept: 'application/json',
        'Content-Type': 'application/x-www-form-urlencoded; charset=utf-8',
        ...(csrfToken ? { 'X-Frappe-CSRF-Token': csrfToken } : {}),
      },
      body: body.toString(),
    })
    const payload = await response.json().catch(() => ({}))
    if (!response.ok || payload.exc) throw new Error(extractErrorMessage(payload, response.statusText || 'The WMS update could not be saved'))
    await bootstrap.reload()
    lastDemoSync.value = new Date().toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
    if (message) toast.success(message)
    return payload.message || payload.data
  } catch (error) {
    toast.error(error.message || 'The WMS update could not be saved')
    return null
  } finally {
    pickActionLoading.value = false
    pickApiBusy = false
  }
}
function setMyTasksTab(tab) { myTasksTab.value = tab; searchValue.value = '' }
// Active is the shared live-progress view (what other people are watching), so it's
// the default filter when deliberately entering My Tasks (bottom nav, a home tile, a
// scan result) - see the explicit myTasksTab.value assignments at those call sites.
// It is NOT a blanket watcher on showMyTasksList: a task just created lands in Open,
// not Active, and a watcher here would stomp that the instant the create flow's own
// setScreen() call flips showMyTasksList true.
const MY_TASKS_DOCTYPE = { Pick: 'Pick Task', Pack: 'Pack Task', Ship: 'Shipment Task', Receive: 'Inbound Package' }
async function fetchApi(method, params) {
  const body = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => body.append(key, value ?? ''))
  const csrfToken = window.csrf_token !== '{{ csrf_token }}' ? window.csrf_token : null
  const response = await window.fetch(`/api/method/soypaq.api.${method}`, {
    method: 'POST',
    cache: 'no-store',
    credentials: 'same-origin',
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/x-www-form-urlencoded; charset=utf-8',
      ...(csrfToken ? { 'X-Frappe-CSRF-Token': csrfToken } : {}),
    },
    body: body.toString(),
  })
  const payload = await response.json().catch(() => ({}))
  if (!response.ok || payload.exc) throw new Error(extractErrorMessage(payload, response.statusText || 'The request failed'))
  return payload.message || payload.data
}
async function uploadPhoto(file) {
  const body = new FormData()
  body.append('file', file)
  body.append('is_private', '0')
  const csrfToken = window.csrf_token !== '{{ csrf_token }}' ? window.csrf_token : null
  const response = await window.fetch('/api/method/upload_file', {
    method: 'POST',
    cache: 'no-store',
    credentials: 'same-origin',
    headers: { Accept: 'application/json', ...(csrfToken ? { 'X-Frappe-CSRF-Token': csrfToken } : {}) },
    body,
  })
  const payload = await response.json().catch(() => ({}))
  if (!response.ok || payload.exc) throw new Error(extractErrorMessage(payload, response.statusText || 'Photo upload failed'))
  return payload.message?.file_url || ''
}
async function openTaskDrawer(task) {
  myTasksDrawerTask.value = task
  myTasksDrawerItems.value = []
  myTasksDrawerSource.value = null
  myTasksDrawerIntegrity.value = null
  myTasksDrawerCreated.value = ''
  myTasksDrawerClaimedAt.value = ''
  myTasksDrawerActivity.value = []
  myTasksDrawerItemsLoading.value = true
  try {
    const result = await fetchApi('get_task_preview', { doctype: MY_TASKS_DOCTYPE[task.kind], name: task.name })
    myTasksDrawerItems.value = result?.items || []
    myTasksDrawerSource.value = result?.source?.name ? result.source : null
    myTasksDrawerIntegrity.value = result?.source_integrity?.status ? result.source_integrity : null
    myTasksDrawerCreated.value = result?.created || ''
    myTasksDrawerClaimedAt.value = result?.claimed_at || ''
    myTasksDrawerActivity.value = result?.activity || []
  } catch (error) {
    toast.error(error.message || 'Could not load task details')
  } finally {
    myTasksDrawerItemsLoading.value = false
  }
}
function closeTaskDrawer() {
  myTasksDrawerTask.value = null
  myTasksDrawerItems.value = []
  myTasksDrawerSource.value = null
  myTasksDrawerIntegrity.value = null
  myTasksDrawerCreated.value = ''
  myTasksDrawerClaimedAt.value = ''
  myTasksDrawerActivity.value = []
}
async function viewShipHistory(task) {
  selectedShipmentTaskName.value = task.name
  await bootstrap.reload()
  shipMode.value = 'completed-detail'
  closeTaskDrawer()
  setScreen('ship')
}
const MY_TASKS_SCREEN = { Pick: 'pick', Pack: 'pack', Ship: 'ship', Receive: 'receive' }
async function goToClaimedTask(task) {
  setScreen(MY_TASKS_SCREEN[task.kind])
  if (task.kind === 'Pick') await openPickActiveOrder(task)
  else if (task.kind === 'Pack') await openPackActiveOrder(task)
  else if (task.kind === 'Ship') await openShipmentTask(task)
  else if (task.kind === 'Receive') await openReceivePackage(task)
}
async function startDrawerTask() {
  const task = myTasksDrawerTask.value
  if (!task) return
  const result = await pickApi('claim_task', { doctype: MY_TASKS_DOCTYPE[task.kind], name: task.name }, `${task.reference} claimed`)
  if (!result) return
  closeTaskDrawer()
  await goToClaimedTask(task)
}
async function releaseDrawerTask() {
  const task = myTasksDrawerTask.value
  if (!task) return
  const result = await pickApi('release_task', { doctype: MY_TASKS_DOCTYPE[task.kind], name: task.name }, `${task.reference} released back to the queue`)
  if (!result) return
  closeTaskDrawer()
  // No tab switch: Active/Open/History are equal filters on one list, not separate
  // screens. The task just drops out of whichever filter no longer matches it.
}
async function cancelDrawerTask() {
  const task = myTasksDrawerTask.value
  if (!task) return
  const result = await pickApi('cancel_task', { doctype: MY_TASKS_DOCTYPE[task.kind], name: task.name }, `${task.reference} cancelled`)
  if (!result) return
  closeTaskDrawer()
}
async function openReceivePackage(pkg) {
  selectedPackageName.value = pkg.name
  await bootstrap.reload()
  // Nothing was expected (a blind package): there is no "Accept package" step, so resume at scanning.
  receiveMode.value = 'work'
}
// Blind receiving's real entry point: no items, no fabricated tracking number - the
// operator has a box in front of them and nothing else. `create_inbound_asn` (the
// button above this one) still requires typing SKUs and quantities before the package
// exists, which is the exact workflow this was built to replace.
const startReceiveOpen = ref(false)
const startReceiveCustomer = ref('')
const startReceiveTracking = ref('')
const startReceiveBusy = ref(false)
const startReceiveClients = ref([])
const startReceiveCanCreate = ref(false)
const startReceiveNew = ref(null) // { name, busy, setting } while the "Create new client" form is open
let startReceivePoll = null
async function loadStartReceiveClients() {
  try {
    const opts = await fetchApi('receive_client_options', {})
    startReceiveClients.value = opts.customers || []
    startReceiveCanCreate.value = !!opts.can_create
  } catch (error) { toast.error(error.message || 'Could not load clients') }
}
function openStartReceiving() {
  startReceiveCustomer.value = ''
  startReceiveTracking.value = ''
  startReceiveNew.value = null
  startReceiveOpen.value = true
  loadStartReceiveClients()
}
function closeStartReceiving() {
  clearInterval(startReceivePoll)
  startReceiveNew.value = null
  startReceiveOpen.value = false
}
async function createStartReceiveClient() {
  const form = startReceiveNew.value
  const name = (form?.name || '').trim()
  if (!name) { toast.error("Enter the client's name"); return }
  form.busy = true
  try {
    const result = await fetchApi('create_client', { customer_name: name })
    form.setting = result.name
    // Onboarding runs in the background (Company, warehouses, first bin); wait until the client can hold stock.
    let tries = 0
    clearInterval(startReceivePoll)
    startReceivePoll = setInterval(async () => {
      tries += 1
      try {
        const status = await fetchApi('client_setup_status', { customer: result.name })
        if (status.ready) {
          clearInterval(startReceivePoll)
          await loadStartReceiveClients()
          startReceiveCustomer.value = result.name
          startReceiveNew.value = null
          toast.success(`${result.name} is ready`)
        } else if (tries >= 40) {
          clearInterval(startReceivePoll)
          if (startReceiveNew.value) { startReceiveNew.value.setting = ''; startReceiveNew.value.busy = false }
          toast.error(`${result.name} was created but setup is still running - reopen this popup in a minute`)
        }
      } catch (error) {
        clearInterval(startReceivePoll)
        if (startReceiveNew.value) { startReceiveNew.value.setting = ''; startReceiveNew.value.busy = false }
        toast.error(error.message || 'Could not check client setup')
      }
    }, 1500)
  } catch (error) {
    form.busy = false
    toast.error(error.message || 'Could not create the client')
  }
}
async function submitStartReceiving() {
  const customer = startReceiveCustomer.value.trim()
  if (!customer) { toast.error('Choose which client this package belongs to'); return }
  startReceiveBusy.value = true
  try {
    const result = await fetchApi('start_receiving_session', {
      customer,
      tracking_number: startReceiveTracking.value.trim(),
    })
    startReceiveOpen.value = false
    selectedPackageName.value = result.name
    await bootstrap.reload()
    receiveMode.value = 'work'
    toast.success(result.resumed ? `Resumed package ${result.name}` : `Receiving started - ${result.name}`)
  } catch (error) {
    toast.error(error.message || 'Could not start receiving')
  } finally {
    startReceiveBusy.value = false
  }
}
async function openShipmentTask(task) {
  selectedShipmentTaskName.value = task.name
  await bootstrap.reload()
  shipMode.value = 'active'
}
// Receiving is discovery: an item not already on the package is the normal case. A known barcode adds
// to its line; an unknown one opens the new-item sheet, prefilled from the client's own catalogue.
const receiveScanQty = ref(1)
const newItem = ref(null)
const lineMenu = ref(null)
const storedResult = ref(null)
const newItemColors = computed(() => [...new Set([...(newItem.value?.options.colors || []), newItem.value?.color].filter(Boolean))])
const newItemSizes = computed(() => [...new Set([...(newItem.value?.options.sizes || []), newItem.value?.size].filter(Boolean))])
const newItemName = computed(() => {
  const form = newItem.value
  if (!form) return ''
  return (form.template || '{PRODUCT} {COLOR} {SIZE}').replace('{PRODUCT}', form.product || '').replace('{COLOR}', form.color || '').replace('{SIZE}', form.size || '').replace(/\s+/g, ' ').trim().toUpperCase()
})
const groupLabel = (group) => String(group || '').replace(`${data.value.receive.package.customer} - `, '')

async function scanReceiveItem() {
  const code = receiveScanValue.value.trim()
  if (!code) { toast.error('Scan or enter an item barcode'); return }
  const qty = Number(receiveScanQty.value) || 1
  const result = await pickApi('receive_scan', { package_name: data.value.receive.package.name, code, quantity: qty }, null)
  if (!result) return
  if (result.resolved === false) { await openNewItem(result.code, qty); return }
  toast.success(`${code} x${qty} added`)
  receiveScanValue.value = ''
  receiveScanQty.value = 1
}
async function openNewItem(code, qty) {
  try {
    const s = await fetchApi('receive_item_suggestion', { package_name: data.value.receive.package.name, code })
    newItem.value = {
      code: s.code, barcode_type: s.barcode_type, related: s.related, template: s.template,
      options: { products: s.products, colors: s.colors, sizes: s.sizes, groups: s.groups },
      product: s.prefill.product, color: s.prefill.color, size: s.prefill.size, group: s.prefill.group, collection: s.prefill.collection,
      productNew: false, colorNew: false, sizeNew: false, qty, flag: false, note: '', busy: false,
    }
  } catch (error) { toast.error(error.message || 'Could not look up this barcode') }
}
function newItemProductChosen(value) {
  const form = newItem.value
  if (value === '__new__') { form.productNew = true; form.product = ''; return }
  form.product = value
  const known = form.options.products.find((p) => p.product === value)
  if (known) { form.group = known.group || form.group; form.collection = known.collection || form.collection }
}
async function submitNewItem() {
  const form = newItem.value
  if (!form.product.trim()) { toast.error('Pick or type the product'); return }
  form.busy = true
  try {
    const result = await pickApi('receive_new_item', {
      package_name: data.value.receive.package.name, code: form.code, product: form.product, color: form.color, size: form.size,
      item_group: form.group, collection: form.collection, quantity: Number(form.qty) || 1, flag: form.flag ? 1 : 0, note: form.note,
    }, `${form.code} added`)
    if (result === null) return
    newItem.value = null
    receiveScanValue.value = ''
    receiveScanQty.value = 1
    await loadStageBins()
  } finally { if (newItem.value) newItem.value.busy = false }
}
async function setLineQty(item, value) {
  const qty = Number(value)
  if (Number.isNaN(qty) || qty < 0) { toast.error('Enter a quantity of 0 or more'); return }
  if (qty === Number(item.received)) return
  await pickApi('set_received_qty', { package_name: data.value.receive.package.name, item_code: item.sku, quantity: qty }, qty ? `${item.sku} set to ${qty}` : `${item.sku} removed`)
}
async function openLineMenu(item) {
  let groups = []
  try { groups = (await fetchApi('receive_item_suggestion', { package_name: data.value.receive.package.name, code: item.sku })).groups } catch { groups = [] }
  if (item.item_group && !groups.includes(item.item_group)) groups = [item.item_group, ...groups]
  lineMenu.value = { item, groups, group: item.item_group, reason: '' }
}
async function lineSetCondition(condition) {
  const menu = lineMenu.value
  const reason = condition === 'Good' ? 'Good' : condition
  if (reason === 'Good' && !['Damaged', 'Hold'].includes(menu.item.status)) { lineMenu.value = null; return }
  await pickApi('flag_receive_item', { package_name: data.value.receive.package.name, item_code: menu.item.sku, reason }, `${menu.item.sku} marked ${condition}`)
  lineMenu.value = null
}
async function lineSetGroup() {
  const menu = lineMenu.value
  const result = await pickApi('set_item_group', { package_name: data.value.receive.package.name, item_code: menu.item.sku, item_group: menu.group }, `${menu.item.sku} moved to ${groupLabel(menu.group)} and flagged`)
  if (result !== null) lineMenu.value = null
}
async function lineFlag() {
  const menu = lineMenu.value
  const result = await pickApi('flag_item', { package_name: data.value.receive.package.name, item_code: menu.item.sku, reason: menu.reason }, `${menu.item.sku} flagged for review`)
  if (result !== null) lineMenu.value = null
}
async function storeReceivePackage() {
  const lines = receiveLines.value.map((line) => ({ item_code: line.sku, name: line.name, qty: line.received, bin: line.assigned_bin }))
  const result = await pickApi('complete_receipt', { package_name: data.value.receive.package.name }, 'Package stored - inventory available')
  if (!result) return
  storedResult.value = { ...result, lines: (result.lines || []).map((l) => ({ ...l, name: lines.find((x) => x.item_code === l.item_code)?.name })) }
  receiveMode.value = 'stored'
}
const receiveStoredLines = computed(() => storedResult.value?.name === data.value.receive.package.name
  ? storedResult.value.lines
  : receiveLines.value.map((line) => ({ item_code: line.sku, name: line.name, qty: line.received, bin: line.assigned_bin })))
const receiveStoredEntry = computed(() => (storedResult.value?.name === data.value.receive.package.name ? storedResult.value.stock_entry : '') || data.value.receive.package.stock_entry || '')
async function receiveNextSameClient() {
  const client = data.value.receive.package.customer
  receiveMode.value = 'tasks'
  openStartReceiving()
  await loadStartReceiveClients()
  if (startReceiveClients.value.includes(client)) startReceiveCustomer.value = client
}
// --- Inventory as an action surface (Pick revision, Phase 1) ---------------------
// Actions hang off the per-bin location card rather than the item, because physical
// work happens at item x bin: "adjust this item in A1", never "adjust this item".
const activeBinAction = ref({ location: null, mode: '' })
const itemDetailTab = ref('locations')
const binAdjustFinal = ref('')
const binAdjustReason = ref('Count Correction')
const binMoveQty = ref('')
const binMoveTarget = ref('')
// "+ New bin": pick the customer, the code defaults to the next free one (A07 after A06).
const newBin = ref(null)
// "Acme - Storage - A02 - AC" to "A02" for compact lines.
const shortBin = (name) => String(name || '').replace(/^.* - Storage - /, '').replace(/ - [A-Z]+$/, '')
async function openNewBin(forMove = false, customer = '', onCreated = null) {
  try {
    const opts = await wmsCall('new_bin_options', customer ? { customer } : {})
    if (!opts.customers.length) { toast.error('No customer has a Storage zone to add a bin to'); return }
    newBin.value = { ...opts, forMove, onCreated, busy: false }
  } catch (error) { toast.error(error.message) }
}
async function newBinCustomerChanged() {
  try { newBin.value.code = (await wmsCall('new_bin_options', { customer: newBin.value.customer })).code } catch (error) { toast.error(error.message) }
}
async function submitNewBin() {
  const form = newBin.value
  form.busy = true
  try {
    const result = await pickApi('create_bin', { customer: form.customer, code: form.code }, 'Bin created')
    if (result === null) return
    if (form.forMove && result?.name) binMoveTarget.value = result.name
    if (form.onCreated && result?.name) await form.onCreated(result)
    newBin.value = null
  } finally { if (newBin.value) newBin.value.busy = false }
}
const binActivity = ref([])
const binActivityLoading = ref(false)
const binActionBusy = ref(false)

function openBinAction(location, mode) {
  activeBinAction.value = { location, mode }
  // Direct entry, not a delta: operators read the correct count off a shelf and type
  // that number, not the difference from what the system currently thinks it is.
  binAdjustFinal.value = String(location.on_hand)
  binAdjustReason.value = 'Count Correction'
  binMoveQty.value = '1'
  binMoveTarget.value = ''
  moveBins.value = []
  if (mode === 'move') loadMoveBins(location)
}
function closeBinAction() {
  activeBinAction.value = { location: null, mode: '' }
}
async function loadBinActivity() {
  const item = selectedInventoryItem.value
  if (!item) { binActivity.value = []; return }
  binActivityLoading.value = true
  try {
    binActivity.value = (await fetchApi('get_bin_activity', { item_code: item.item_code, limit: 20 })) || []
  } catch (error) {
    binActivity.value = []
  } finally {
    binActivityLoading.value = false
  }
}
async function loadGlobalActivity() {
  globalActivityLoading.value = true
  try {
    globalActivity.value = (await fetchApi('get_bin_activity', { limit: 100 })) || []
  } catch (error) {
    globalActivity.value = []
  } finally {
    globalActivityLoading.value = false
  }
}
// An activity entry sourced from a WMS task (Pick/Pack/Ship/Receive) opens the same
// drawer My Tasks uses - contents, activity, claim state - instead of bouncing to Desk.
// Anything else (a raw Stock Reconciliation, a Purchase Receipt) has no task drawer to
// show, so it still falls back to opening the ERPNext record directly.
const ACTIVITY_SOURCE_TO_KIND = { 'Pick Task': 'Pick', 'Pack Task': 'Pack', 'Shipment Task': 'Ship', 'Inbound Package': 'Receive' }
function openActivityEntry(entry) {
  const kind = ACTIVITY_SOURCE_TO_KIND[entry.source_type]
  if (kind && entry.source_name) {
    openTaskDrawer({ kind, name: entry.source_name, reference: entry.source_name })
    return
  }
  openDesk(entry.route)
}
async function submitBinAdjust(location) {
  const final = Number(binAdjustFinal.value)
  if (binAdjustFinal.value === '' || Number.isNaN(final) || final < 0) { toast.error('Enter the correct quantity'); return }
  const delta = final - Number(location.on_hand)
  if (!delta) { toast.error('That matches the current quantity - nothing to adjust'); return }
  binActionBusy.value = true
  try {
    // adjust_bin_qty is still a delta endpoint - the direct-value entry is purely a UI
    // convenience, computed against on_hand as read when the popup opened.
    await pickApi('adjust_bin_qty', {
      item_code: selectedInventoryItem.value.item_code,
      warehouse: location.warehouse,
      quantity_delta: delta,
      reason_code: binAdjustReason.value,
    }, `${selectedInventoryItem.value.item_code} set to ${final}`)
    closeBinAction()
    await loadBinActivity()
  } finally { binActionBusy.value = false }
}
async function submitBinMove(location) {
  const qty = Number(binMoveQty.value)
  const target = (binMoveTarget.value || '').trim()
  if (!qty || qty <= 0) { toast.error('Enter a quantity to move'); return }
  if (!target) { toast.error('Scan or enter a destination bin'); return }
  binActionBusy.value = true
  try {
    await pickApi('move_bin_stock', {
      item_code: selectedInventoryItem.value.item_code,
      from_warehouse: location.warehouse,
      to_warehouse: target,
      quantity: qty,
      reason_code: 'Physical Recount',
    }, `Moved ${qty} to ${target}`)
    closeBinAction()
    await loadBinActivity()
  } finally { binActionBusy.value = false }
}
// "Start pick from this bin" (Inventory > Bins) opens the scan-first pick builder listing that bin's items.
// The other entry point is New Pick Task on the Pick screen.
function openPickFromBin(bin) { openPickBuilder({ code: bin.name }) }
watch(selectedItemCode, (code) => {
  closeBinAction()
  itemDetailTab.value = 'locations'
  if (code) loadBinActivity()
  else binActivity.value = []
})

// A client's bins for the pickers: where an item already lives first, then the rest, then "+ New bin".
const stageBins = ref([])
const moveBins = ref([])
async function loadStageBins() {
  const pkg = data.value.receive?.package
  if (!pkg?.name) { stageBins.value = []; return }
  try {
    const result = await wmsCall('client_bins', { customer: pkg.customer || '', item_codes: JSON.stringify((pkg.items || []).map((i) => i.sku)) })
    stageBins.value = result.bins || []
  } catch (error) { toast.error(error.message || 'Could not load bins') }
}
function binGroups(bins, sku, exclude = '') {
  const usable = bins.filter((b) => b.warehouse !== exclude)
  return { held: usable.filter((b) => (b.held || {})[sku] > 0), other: usable.filter((b) => !((b.held || {})[sku] > 0)) }
}
async function stageBinChosen(item, value) {
  if (value !== '__new__') return
  delete stagingBinInputs.value[item.sku]
  await openNewBin(false, data.value.receive.package.customer, async (created) => {
    await loadStageBins()
    stagingBinInputs.value[item.sku] = created.name
  })
}
const moveBinsCustomer = ref('')
async function loadMoveBins(location) {
  try {
    const result = await wmsCall('client_bins', { near_warehouse: location.warehouse, item_codes: JSON.stringify([selectedInventoryItem.value?.item_code].filter(Boolean)) })
    moveBins.value = result.bins || []
    moveBinsCustomer.value = result.customer || ''
  } catch (error) { toast.error(error.message || 'Could not load bins') }
}
async function moveBinChosen(value) {
  if (value !== '__new__') return
  binMoveTarget.value = ''
  // forMove makes the new bin the destination; reload so it shows in the list too.
  await openNewBin(true, moveBinsCustomer.value, () => loadMoveBins(activeBinAction.value.location))
}
watch(receiveMode, (mode) => { if (mode === 'work') loadStageBins() })
// Put-away suggestion per line: a bin that already holds the item, else the last bin used in this box.
const lastStageBin = ref('')
function applyBinDefaults() {
  for (const line of receiveStageableRows.value) {
    if (stagingBinInputs.value[line.sku]) continue
    const held = binGroups(stageBins.value, line.sku).held[0]
    const lastBin = lastStageBin.value || [...receiveLines.value].reverse().find((l) => l.assigned_bin)?.assigned_bin
    const fallback = stageBins.value.find((b) => b.warehouse === lastBin)
    if (held || fallback) stagingBinInputs.value[line.sku] = (held || fallback).warehouse
  }
}
watch(stageBins, applyBinDefaults)
// A new line needs to know where that item already lives: reload the client's bins when lines are added.
watch(() => receiveLines.value.map((l) => l.sku).join('|'), (now, before) => {
  if (receiveMode.value === 'work' && now.split('|').some((sku) => sku && !(before || '').split('|').includes(sku))) loadStageBins()
})
async function stageAllSuggested() {
  for (const line of [...receiveStageableRows.value]) {
    const bin = stagingBinInputs.value[line.sku]
    if (bin) await stageItem(line, bin)
  }
}
async function stageItem(item, binCode) {
  const code = (binCode || '').trim()
  if (!code) { toast.error('Scan or enter a bin code'); return }
  const result = await pickApi('stage_item', { package_name: data.value.receive.package.name, item_code: item.sku, bin_code: code }, `${item.sku} staged to ${shortBin(code)}`)
  delete stagingBinInputs.value[item.sku]
  if (result !== null) { lastStageBin.value = code; applyBinDefaults() }
}
function openStageScanner(item) {
  stagingTargetSku.value = item.sku
  openScanner('stage-bin')
}
// Every bin is confirmed on the server: by scanning the bin, scanning an item in it (a scan proves presence),
// or "I'm here" for tapping. A single-bin task's server gate expects the task's own bin code.
// Resolves falsy only when the server refused.
async function confirmBinGroup(bin) {
  const group = pickBinGroups.value.find((row) => row.bin === bin)
  if (!group || binIsConfirmed(group)) return true
  const code = pickBinGroups.value.length > 1 ? bin : (data.value.pick.bin || bin)
  return pickApi('confirm_pick_location', { task_name: pickTaskName.value, location_code: code }, `Bin ${bin} confirmed`)
}
const binIsConfirmed = (group) => group.items.every((item) => item.bin_confirmed) || (pickBinGroups.value.length <= 1 && pickLocationConfirmed.value)
// A scanned/typed bin code: the full name or the short code (A02), as the server accepts.
function findPickBin(code) {
  const c = String(code || '').trim().toLowerCase()
  if (!c) return null
  return pickBinGroups.value.find((group) => { const bin = group.bin.toLowerCase(); return bin === c || bin.includes(` - ${c} - `) || bin.endsWith(` - ${c}`) }) || null
}
async function pickItem(item) {
  selectedPickSku.value = item.sku
  pickActionTag.value = 'row'
  if (!(await confirmBinGroup(item.source_bin || item.source_warehouse || 'No bin assigned'))) return
  await pickApi('pick_item', { task_name: pickTaskName.value, item_code: item.sku, quantity: 1 }, `${item.sku} picked and saved`)
}
async function unpickItem(item) {
  selectedPickSku.value = item.sku
  pickActionTag.value = 'row'
  await pickApi('unpick_item', { task_name: pickTaskName.value, item_code: item.sku, quantity: 1 }, `${item.sku} quantity reduced`)
}
async function scanPickItem() {
  const code = pickScanValue.value.trim()
  const item = pickRows.value.find((row) => row.sku === code)
  if (!item) {
    const binGroup = findPickBin(code)
    if (binGroup) { pickScanValue.value = ''; await confirmBinGroup(binGroup.bin); return }
    pickIssueReason.value = 'Wrong Item'
    toast.error(`${code || 'That barcode'} is not an item or bin on this pick task`)
    return
  }
  selectedPickSku.value = item.sku
  pickActionTag.value = 'scan'
  // A successful barcode scan is itself proof of physical presence at the bin - no
  // separate "I'm here" tap should be required after this, same as the manual +/-
  // buttons intend (pickItem calls this too, it's just unreachable while disabled).
  if (!(await confirmBinGroup(item.source_bin || item.source_warehouse || 'No bin assigned'))) return
  await pickApi('pick_item', { task_name: pickTaskName.value, item_code: item.sku, quantity: 1 }, `${item.sku} picked and saved`)
  pickScanValue.value = ''
}
function loadScannerLib() {
  if (window.Html5Qrcode) return Promise.resolve()
  if (window.__soypaqScannerLibPromise) return window.__soypaqScannerLibPromise
  window.__soypaqScannerLibPromise = new Promise((resolve, reject) => {
    const script = document.createElement('script')
    script.src = '/assets/frappe/node_modules/html5-qrcode/html5-qrcode.min.js'
    script.onload = () => resolve()
    script.onerror = () => reject(new Error('Could not load the barcode scanner'))
    document.head.appendChild(script)
  })
  return window.__soypaqScannerLibPromise
}
async function openScanner(target) {
  scannerTarget.value = target
  scannerOpen.value = true
  scannerStarting.value = true
  try {
    await loadScannerLib()
    await new Promise((resolve) => requestAnimationFrame(resolve))
    scannerHandler = new window.Html5Qrcode('wms-scanner-area')
    await scannerHandler.start(
      { facingMode: 'environment' },
      { fps: 10, qrbox: 220 },
      (decodedText) => onScanDecoded(decodedText),
      () => {},
    )
  } catch (error) {
    toast.error(error.message || 'Could not access the camera')
    closeScanner()
  } finally {
    scannerStarting.value = false
  }
}
function onScanDecoded(decodedText) {
  const code = (decodedText || '').trim()
  if (!code) return
  if (scannerTarget.value === 'receive-sku') {
    closeScanner()
    receiveScanValue.value = code
    scanReceiveItem()
  } else if (scannerTarget.value === 'pack-sku') {
    closeScanner()
    packScanValue.value = code
    scanPackItem()
  } else if (scannerTarget.value === 'builder') {
    closeScanner()
    builderScanSubmit(code)
  } else if (scannerTarget.value === 'stage-bin') {
    closeScanner()
    const item = data.value.receive.package.items.find((row) => row.sku === stagingTargetSku.value)
    if (item) stageItem(item, code)
  } else {
    pickScanValue.value = code
    closeScanner()
    scanPickItem()
  }
}
function closeScanner() {
  const handler = scannerHandler
  scannerHandler = null
  scannerOpen.value = false
  if (handler) {
    handler.stop().then(() => handler.clear()).catch(() => {})
  }
}
// Light call for lookups: no bootstrap reload and not gated by pickApiBusy, so scanning stays instant.
async function wmsCall(method, params) {
  const body = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => body.append(key, value ?? ''))
  const csrfToken = window.csrf_token !== '{{ csrf_token }}' ? window.csrf_token : null
  const response = await window.fetch(`/api/method/soypaq.api.${method}`, {
    method: 'POST',
    cache: 'no-store',
    credentials: 'same-origin',
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/x-www-form-urlencoded; charset=utf-8',
      ...(csrfToken ? { 'X-Frappe-CSRF-Token': csrfToken } : {}),
    },
    body: body.toString(),
  })
  const payload = await response.json().catch(() => ({}))
  if (!response.ok || payload.exc) throw new Error(extractErrorMessage(payload, response.statusText || 'Lookup failed'))
  return payload.message
}
function scanFeedback(ok) {
  if (vibration.value && navigator.vibrate) navigator.vibrate(ok ? 40 : [80, 60, 80])
  if (!sound.value) return
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)()
    const osc = ctx.createOscillator()
    osc.frequency.value = ok ? 880 : 220
    osc.connect(ctx.destination)
    osc.start()
    osc.stop(ctx.currentTime + (ok ? 0.08 : 0.25))
    osc.onended = () => ctx.close()
  } catch { /* feedback is optional */ }
}
function focusBuilderInput() {
  requestAnimationFrame(() => builderInput.value?.$el?.querySelector('input')?.focus({ preventScroll: true }))
}
function openPickBuilder(seed) {
  builderLines.value = []
  builderBin.value = null
  builderScan.value = ''
  builderEditKey.value = ''
  builderOpen.value = true
  focusBuilderInput()
  wmsCall('preview_pick_task_names', { count: 8 }).then((names) => { builderNames.value = names || [] }).catch(() => { builderNames.value = [] })
  if (seed?.code) builderScanSubmit(seed.code)
}
function closePickBuilder() { builderOpen.value = false; builderEditKey.value = '' }
const builderLoc = (line) => line.locations.find((loc) => loc.warehouse === line.warehouse) || null
const builderAvailable = (line) => builderLoc(line)?.available ?? 0
const builderOver = (line) => Number(line.quantity) > builderAvailable(line)
const builderGroups = computed(() => {
  const groups = new Map()
  for (const line of builderLines.value) {
    if (!groups.has(line.warehouse)) groups.set(line.warehouse, { warehouse: line.warehouse, label: builderLoc(line)?.label || line.warehouse, lines: [] })
    groups.get(line.warehouse).lines.push(line)
  }
  return [...groups.values()]
})
// A preview of the naming series (the real name is assigned on create). One task covers every bin.
const builderTaskName = computed(() => builderNames.value[0] || 'New pick task')
const builderUnits = computed(() => builderLines.value.reduce((sum, line) => sum + (Number(line.quantity) || 0), 0))
const builderCanCreate = computed(() => builderLines.value.length > 0 && builderLines.value.every((line) => Number(line.quantity) > 0 && !builderOver(line)))
const builderEditLine = computed(() => builderLines.value.find((line) => line.item_code === builderEditKey.value) || null)
function addBuilderItem(res) {
  const existing = builderLines.value.find((line) => line.item_code === res.item_code)
  if (existing) {
    if (Number(existing.quantity) + 1 > builderAvailable(existing)) { scanFeedback(false); toast.error(`No more ${existing.item_name} left in ${builderLoc(existing)?.label || existing.warehouse}`); return }
    existing.quantity = Number(existing.quantity) + 1
  } else {
    if (!res.locations.length) { scanFeedback(false); toast.error(`${res.item_name} has no stock in any bin`); return }
    const best = res.locations.find((loc) => loc.warehouse === res.default_warehouse)
    if (!best || best.available < 1) { scanFeedback(false); toast.error(`${res.item_name} has none left to pick`); return }
    // Keep going in the bin the sheet is already using (scanned bin, else the last line's): the server
    // returns default_warehouse for that hint, else the bin with the most available.
    builderLines.value.unshift({ item_code: res.item_code, item_name: res.item_name, image: res.image, uom: res.uom, locations: res.locations, warehouse: res.default_warehouse, quantity: 1 })
  }
  builderFlashKey.value = res.item_code
  scanFeedback(true)
}
async function builderScanSubmit(raw) {
  const code = String(raw ?? builderScan.value).trim()
  builderScan.value = ''
  focusBuilderInput()
  if (!code || builderBusy.value) return
  // Fast path: the code is already a line's item code, so a repeat scan needs no round trip.
  if (builderLines.value.some((line) => line.item_code === code)) { addBuilderItem({ item_code: code }); return }
  builderBusy.value = true
  try {
    const hint = builderBin.value?.warehouse || builderLines.value[0]?.warehouse || ''
    const res = await wmsCall('resolve_scan', { code, warehouse: hint })
    if (!res.resolved) { scanFeedback(false); toast.error(`No item or bin found for ${code}`); return }
    if (res.kind === 'bin') { builderBin.value = res; scanFeedback(true); return }
    addBuilderItem(res)
  } catch (error) {
    scanFeedback(false)
    toast.error(error.message || 'Lookup failed')
  } finally {
    builderBusy.value = false
    focusBuilderInput()
  }
}
// In the scanned bin's list an item reads "N available" until it is in the sheet from that bin, then "N left".
const builderBinLine = (item) => builderLines.value.find((row) => row.item_code === item.item_code && row.warehouse === builderBin.value?.warehouse)
const builderBinLeft = (item) => Math.max(0, item.available - Number(builderBinLine(item)?.quantity || 0))
function builderBinCount(item) {
  return builderBinLine(item) ? `${formatQty(builderBinLeft(item))} left` : `${formatQty(item.available)} available`
}
// Pick everything available in the listed bin: each item at its available quantity.
async function addAllFromBuilderBin() {
  const bin = builderBin.value
  if (!bin) return
  for (const item of bin.items) {
    if (item.available <= 0) continue
    await builderScanSubmit(item.item_code)
    const line = builderLines.value.find((row) => row.item_code === item.item_code)
    if (line && line.warehouse === bin.warehouse) line.quantity = item.available
  }
}
// Never above what is available in the line's bin (and never below 1; use Remove to drop a line).
function setBuilderQty(line, qty) { line.quantity = Math.min(Math.max(1, Number(qty) || 1), Math.max(1, builderAvailable(line))) }
function changeBuilderBin(line, loc) {
  if (loc.available < 1) return
  line.warehouse = loc.warehouse
  setBuilderQty(line, line.quantity)
}
function removeBuilderLine(line) {
  builderLines.value = builderLines.value.filter((row) => row !== line)
  builderEditKey.value = ''
}
async function submitPickBuilder() {
  if (!builderCanCreate.value) return
  const items = builderLines.value.map((line) => ({ item_code: line.item_code, quantity: Number(line.quantity), warehouse: line.warehouse }))
  pickActionTag.value = 'create'
  const result = await pickApi('create_pick_task', { items: JSON.stringify(items) }, '')
  if (!result) return
  toast.success(`${result.name} created`)
  closePickBuilder()
  receiveMode.value = 'tasks'
  pickMode.value = 'tasks'
  packMode.value = 'tasks'
  shipMode.value = 'tasks'
  myTasksTab.value = 'open'
  setScreen('pick')
}
function openCreateForm(type) {
  if (type === 'pick') { openPickBuilder(); return }
  createFormType.value = type
  createCustomer.value = ''
  createWarehouse.value = ''
  createPackageType.value = 'Carton Box'
  createCarrier.value = type === 'receive' ? 'Other' : 'UPS'
  createItems.value = [{ item_code: '', quantity: 1 }]
  createFormOpen.value = true
}
function closeCreateForm() { createFormOpen.value = false }
function addCreateItemRow() { createItems.value.push({ item_code: '', quantity: 1 }) }
function removeCreateItemRow(index) { createItems.value.splice(index, 1) }
async function submitCreateForm() {
  const items = createItems.value
    .filter((row) => row.item_code.trim())
    .map((row) => ({ item_code: row.item_code.trim(), quantity: Number(row.quantity) || 0 }))
  if (!items.length) { toast.error('Add at least one item line'); return }

  const methodByType = {
    receive: 'create_inbound_asn',
    pick: 'create_pick_task',
    pack: 'create_pack_task',
    ship: 'create_shipment_task',
  }
  const params = { items: JSON.stringify(items) }
  if (createCustomer.value.trim()) params.customer = createCustomer.value.trim()
  if (createFormType.value === 'receive') {
    if (createWarehouse.value.trim()) params.target_warehouse = createWarehouse.value.trim()
    params.carrier = createCarrier.value
  } else if (createFormType.value === 'pick') {
    if (createWarehouse.value.trim()) params.warehouse = createWarehouse.value.trim()
  } else if (createFormType.value === 'pack') {
    params.package_type = createPackageType.value
  } else if (createFormType.value === 'ship') {
    params.carrier = createCarrier.value
  }

  pickActionTag.value = 'create'
  const result = await pickApi(methodByType[createFormType.value], params, 'Test task created in ERPNext')
  if (!result) return
  closeCreateForm()
  receiveMode.value = 'tasks'
  pickMode.value = 'tasks'
  packMode.value = 'tasks'
  shipMode.value = 'tasks'
  myTasksTab.value = 'open'
  setScreen(createFormType.value)
}
function openStageList(kind) {
  receiveMode.value = 'tasks'
  pickMode.value = 'tasks'
  packMode.value = 'tasks'
  shipMode.value = 'tasks'
  myTasksTab.value = 'active'
  setScreen(kind)
}
async function openPickActiveOrder(task) {
  selectedPickTaskName.value = task.name
  await bootstrap.reload()
  pickMode.value = 'active'
  selectedPickSku.value = ''
}
async function goToPackOrder() {
  const packName = data.value.pick.context.pack_task_name
  if (!packName) return toast.info('No Pack Task is linked to this pick yet')
  selectedPackTaskName.value = packName
  await bootstrap.reload()
  packMode.value = 'active'
  setScreen('pack')
}
const pickExceptionReason = ref('')
const pickExceptionNote = ref('')
const pickExceptionImage = ref('')
const pickExceptionUploading = ref(false)
const pickPhotoInput = ref(null)
function openPickItemDrawer(item) {
  if (item?.sku) selectedPickSku.value = item.sku
  pickExceptionReason.value = ''
  pickExceptionNote.value = ''
  pickExceptionImage.value = ''
  pickMode.value = 'drawer'
}
function selectPickException(reason) {
  pickExceptionReason.value = pickExceptionReason.value === reason ? '' : reason
  pickExceptionNote.value = ''
  pickExceptionImage.value = ''
}
async function handlePickExceptionPhoto(event) {
  const file = event.target.files?.[0]
  if (!file) return
  pickExceptionUploading.value = true
  try {
    pickExceptionImage.value = await uploadPhoto(file)
  } catch (error) {
    toast.error(error.message || 'Photo upload failed')
  } finally {
    pickExceptionUploading.value = false
    event.target.value = ''
  }
}
async function submitPickException() {
  if (!pickExceptionReason.value) return
  await flagPickItem(pickExceptionReason.value, false, pickExceptionNote.value, pickExceptionImage.value)
}
async function flagPickItem(reason, handpick = false, note = '', image = '') {
  if (!selectedPickItem.value) return toast.info('Choose an item line first')
  await pickApi(
    'flag_pick_item',
    { task_name: pickTaskName.value, item_code: selectedPickItem.value.sku, reason, handpick: handpick ? 1 : 0, quantity: handpick ? 1 : 0, note, image },
    handpick ? `${selectedPickItem.value.sku} handpicked and saved` : `${selectedPickItem.value.sku} marked ${reason}`,
  )
  pickIssueReason.value = reason
  pickExceptionReason.value = ''
  pickExceptionNote.value = ''
  pickExceptionImage.value = ''
  pickMode.value = 'active'
}
async function pickAll() {
  await pickApi('pick_all', { task_name: pickTaskName.value }, 'All remaining task quantities saved')
}
const pickCompleteConfirmOpen = ref(false)
function completePick() { pickCompleteConfirmOpen.value = true }
function closePickCompleteConfirm() { pickCompleteConfirmOpen.value = false }
async function resolvePickComplete(skipDownstream) {
  pickActionTag.value = 'complete'
  const result = await pickApi(
    'complete_pick',
    { task_name: pickTaskName.value, skip_downstream: skipDownstream ? 1 : 0 },
    skipDownstream ? 'Pick completed - not sent to packing' : 'Pick completed and released to packing',
  )
  closePickCompleteConfirm()
  if (!result) return
  pickMode.value = 'tasks'
  myTasksTab.value = 'history'
}
async function openPackActiveOrder(task) {
  selectedPackTaskName.value = task.name
  await bootstrap.reload()
  packMode.value = 'active'
}
async function goToShipmentOrder() {
  const shipName = data.value.pack.context.shipment_task_name
  if (!shipName) return toast.info('No Shipment Task is linked to this pack yet')
  selectedShipmentTaskName.value = shipName
  await bootstrap.reload()
  shipMode.value = 'active'
  setScreen('ship')
}
async function packItem(item) {
  await mutate(packItemRequest, { task_name: packTaskName.value, item_code: item.sku, quantity: 1 }, `${item.sku} packed and saved`)
}
async function scanPackItem() {
  const code = packScanValue.value.trim()
  const item = data.value.pack.items.find((row) => row.sku === code)
  if (!item) return toast.error(`Item ${code || 'barcode'} is not expected in this container`)
  if (Number(item.packed || 0) >= Number(item.picked || 0)) return toast.info(`${item.sku} has no remaining picked quantity to pack`)
  await packItem(item)
  packScanValue.value = ''
}
async function packAll() {
  await mutate(packAllRequest, { task_name: packTaskName.value }, 'All picked quantities saved to this container')
}
async function unpackItem(item) {
  await mutate(unpackItemRequest, { task_name: packTaskName.value, item_code: item.sku, quantity: 1 }, `${item.sku} removed from the box`)
}
async function completePack() {
  await mutate(completePackRequest, { task_name: packTaskName.value }, 'Box confirmed and released to shipping')
}
const emptyShipForm = () => ({ name: '', company: '', line_1: '', line_2: '', city: '', state: '', postal_code: '', country: 'US', phone: '', email: '', weight_kg: '', length_cm: '', width_cm: '', height_cm: '' })
const shipForm = ref(emptyShipForm())
const shipFormTask = ref('')
const shipToFields = [['name', 'Recipient name'], ['company', 'Company'], ['line_1', 'Address line 1'], ['line_2', 'Address line 2'], ['city', 'City'], ['state', 'State / province'], ['postal_code', 'Postal code'], ['country', 'Country (2 letters)'], ['phone', 'Phone'], ['email', 'Email']]
const parcelFields = [['weight_kg', 'Weight (kg)'], ['length_cm', 'Length (cm)'], ['width_cm', 'Width (cm)'], ['height_cm', 'Height (cm)']]
// Prefill once per shipment task (saved entry, else the order's address); later reloads don't overwrite typing.
watch(() => data.value.ship, (ship) => {
  if (!ship?.name || shipFormTask.value === ship.name) return
  shipFormTask.value = ship.name
  const parcel = Object.fromEntries(Object.entries(ship.parcel || {}).map(([key, value]) => [key, value || '']))
  shipForm.value = { ...emptyShipForm(), ...Object.fromEntries(Object.entries(ship.ship_to || {}).filter(([, value]) => value)), ...parcel }
}, { immediate: true })
async function generateLabel() {
  const { weight_kg, length_cm, width_cm, height_cm, ...shipTo } = shipForm.value
  await pickApi('generate_shipment_label', {
    task_name: data.value.ship.name,
    ship_to: JSON.stringify(shipTo),
    parcel: JSON.stringify({ weight_kg, length_cm, width_cm, height_cm }),
  }, 'Shipping label generated and saved')
}
async function completeShipment() {
  const result = await pickApi('mark_shipment_shipped', { task_name: data.value.ship.name }, 'Shipment marked shipped in ERPNext')
  if (!result) return
  shipMode.value = 'tasks'
  myTasksTab.value = 'history'
}

let refreshTimer
let clockTimer
onMounted(() => {
  window.addEventListener('focus', reloadQuietly)
  refreshTimer = window.setInterval(reloadQuietly, 12000)
  clockTimer = window.setInterval(() => { nowTick.value = Date.now() }, 1000)
})
onBeforeUnmount(() => {
  window.removeEventListener('focus', reloadQuietly)
  window.clearInterval(refreshTimer)
  window.clearInterval(clockTimer)
  if (scannerHandler) closeScanner()
})
</script>

<template>
  <FrappeUIProvider>
    <div class="wms-page min-h-screen py-0 text-ink-gray-9 sm:py-7">
      <main class="wms-phone relative mx-auto max-w-[400px] overflow-hidden bg-surface-base shadow-xl sm:min-h-[700px] sm:rounded-5 sm:border sm:border-outline-green-3">
        <header class="wms-brand text-ink-gray-1">
          <div class="wms-brand-row flex items-center justify-between px-3">
            <Button variant="ghost" theme="gray" class="wms-logo-button text-ink-gray-1" @click="goHome"><div class="flex items-center gap-2"><span class="lucide-box size-7" aria-hidden="true" /><p class="text-xl-semibold">SoyPaq</p></div></Button>
            <Button variant="ghost" theme="gray" class="wms-profile" @click="setScreen('settings')"><div class="flex items-center gap-2 rounded-4 bg-surface-base px-2 py-1.5 text-ink-gray-9"><Avatar :label="data.operator.name" size="sm" /><div class="max-w-24 text-left"><p class="truncate text-2xs-semibold">{{ data.operator.name }}</p><p class="truncate text-2xs text-ink-gray-5">{{ data.operator.role }}</p></div><span class="lucide-chevron-down size-3 text-ink-green-6" aria-hidden="true" /></div></Button>
          </div>
          <div class="wms-titlebar flex items-center justify-between px-3">
            <Button v-if="screen !== 'home'" variant="ghost" theme="gray" icon="lucide-arrow-left" aria-label="Back" class="text-ink-gray-1" @click="goBack" /><span v-else class="size-8" />
            <p class="text-sm-semibold text-ink-gray-1">{{ title }}</p>
            <Button v-if="screen === 'home'" variant="ghost" theme="gray" icon="lucide-search" aria-label="Search" class="text-ink-gray-1" @click="setScreen('search')" />
            <Button v-else-if="screen === 'inventory'" variant="ghost" theme="gray" icon="lucide-refresh-cw" aria-label="Refresh inventory" class="text-ink-gray-1" :loading="bootstrap.loading" @click="refresh('Inventory refreshed from ERPNext')" /><Button v-else-if="showMyTasksList" variant="ghost" theme="gray" icon="lucide-refresh-cw" aria-label="Refresh tasks" class="text-ink-gray-1" :loading="bootstrap.loading" @click="refresh('Tasks refreshed from ERPNext')" /><span v-else class="size-8" />
          </div>
        </header>

        <section class="wms-scroll px-3 pb-7 pt-3">
          <div v-if="bootstrap.loading && !bootstrap.data" class="space-y-4 pt-4"><LoadingText :lines="6" /></div>
          <template v-else>
            <section v-if="screen === 'home'" class="space-y-4">
              <p class="text-base-semibold">My work</p>
              <div class="grid grid-cols-2 gap-3">
                <Button v-for="action in [
                  { key: 'receive', label: 'Receive', meta: 'ASNs to receive', icon: 'lucide-truck', count: data.stats.receive },
                  { key: 'pick', label: 'Pick', meta: 'Orders to pick', icon: 'lucide-map-pin', count: data.stats.pick },
                  { key: 'pack', label: 'Pack', meta: 'Orders to pack', icon: 'lucide-package-check', count: data.stats.pack },
                  { key: 'ship', label: 'Ship', meta: 'Shipments to send', icon: 'lucide-send', count: data.stats.ship },
                ]" :key="action.label" variant="outline" theme="gray" class="wms-work-tile-big !justify-start" @click="openStageList(action.key)"><div class="relative flex w-full flex-col items-center gap-2"><span :class="[action.icon, 'size-10 text-ink-green-6']" aria-hidden="true" /><Badge v-if="action.count" :label="String(action.count)" theme="green" variant="solid" class="absolute right-0 top-0" /><span class="text-base-semibold">{{ action.label }}</span><span class="text-2xs text-ink-gray-5">{{ action.meta }}</span></div></Button>
              </div>
              <div>
                <p class="mb-2 text-base-semibold">Dashboard</p>
                <TextInput v-model="homeSearchValue" placeholder="Search (coming soon)" class="mb-2" />
                <div class="wms-stat-grid grid grid-cols-3 divide-x divide-outline-gray-2 rounded-4 border border-outline-gray-2 bg-surface-base py-2 text-center">
                  <div><p class="text-lg-semibold">{{ formatQty(inventory.summary.sku_count) }}</p><p class="text-2xs text-ink-gray-5">Live items</p></div>
                  <div><p class="text-lg-semibold">{{ inventory.summary.stocked_bin_count }}</p><p class="text-2xs text-ink-gray-5">Warehouses (bins)</p></div>
                  <div><p class="text-lg-semibold">{{ formatCurrency(inventory.summary.stock_value) }}</p><p class="text-2xs text-ink-gray-5">Stock value</p></div>
                </div>
              </div>
            </section>

            <section v-else-if="showMyTasksList" class="space-y-3">
              <Button v-if="myTasksScreenKind === 'Receive'" label="Start receiving (scan as you go)" icon-left="lucide-package-plus" variant="solid" theme="green" class="w-full" @click="openStartReceiving" />
              <Button v-if="myTasksScreenKind && myTasksScreenKind !== 'Receive'" :label="MY_TASKS_CREATE_LABEL[myTasksScreenKind]" icon-left="lucide-plus" variant="outline" :theme="myTasksScreenKind === 'Receive' ? 'gray' : 'green'" class="w-full" @click="openCreateForm(myTasksScreenKind.toLowerCase())" />
              <TextInput v-model="searchValue" label="Search tasks" />
              <div class="grid grid-cols-3 gap-2 rounded-4 border border-outline-gray-2 bg-surface-base p-1">
                <Button :label="myTasksActive.length ? `Active (${myTasksActive.length})` : 'Active'" :variant="myTasksTab === 'active' ? 'solid' : 'ghost'" theme="green" @click="setMyTasksTab('active')" />
                <Button :label="myTasksOpen.length ? `Open (${myTasksOpen.length})` : 'Open'" :variant="myTasksTab === 'open' ? 'solid' : 'ghost'" theme="gray" @click="setMyTasksTab('open')" />
                <Button label="History" :variant="myTasksTab === 'history' ? 'solid' : 'ghost'" theme="gray" @click="setMyTasksTab('history')" />
              </div>
              <div v-for="task in myTasksCurrentList" :key="`${task.kind}-${task.name}`" class="rounded-4 border border-outline-gray-2 bg-surface-base p-3 shadow-sm" @click="openTaskDrawer(task)">
                <div class="flex items-start gap-3">
                  <div class="wms-item-thumb shrink-0"><img v-if="task.image" :src="task.image" :alt="task.reference" /><span v-else class="lucide-shirt size-5 text-ink-green-6" aria-hidden="true" /></div>
                  <div class="min-w-0 flex-1">
                    <div class="flex items-center gap-1.5"><Badge :label="task.kind" theme="green" variant="subtle" /><p class="truncate text-sm-semibold">{{ task.reference }}</p></div>
                    <p class="mt-1 truncate text-xs text-ink-gray-5">{{ task.customer }} - {{ task.status }}</p>
                    <p v-if="task.assigned_to?.id" class="mt-1 truncate text-2xs text-ink-green-6">{{ myTasksTab === 'history' ? 'Done by' : 'Claimed by' }} {{ task.assigned_to.name }}</p>
                    <p v-if="task.created" class="mt-1 truncate text-2xs text-ink-gray-4">Created {{ formatDateTime(task.created) }}</p>
                  </div>
                  <span class="lucide-chevron-right size-4 shrink-0 text-ink-gray-4" aria-hidden="true" />
                </div>
              </div>
              <div v-if="!myTasksCurrentList.length" class="py-10 text-center">
                <span class="lucide-clipboard-check mx-auto size-7 text-ink-gray-4" aria-hidden="true" />
                <p class="mt-2 text-sm text-ink-gray-5">{{ myTasksTab === 'open' ? 'No open tasks.' : myTasksTab === 'active' ? 'Nobody has an active task right now.' : 'No completed tasks yet.' }}</p>
              </div>
            </section>

            <section v-else-if="screen === 'search'" class="space-y-4">
              <div class="grid grid-cols-2 gap-2"><Button label="Barcode scan" :variant="scanMode === 'barcode' ? 'solid' : 'outline'" theme="green" @click="scanMode = 'barcode'" /><Button label="Manual entry" :variant="scanMode === 'manual' ? 'solid' : 'outline'" theme="gray" @click="scanMode = 'manual'" /></div>
              <div class="rounded-4 border border-outline-green-3 bg-surface-green-1 p-3"><p class="text-2xs-semibold text-ink-green-6">Scan or enter a record</p><TextInput v-model="scanValue" label="Barcode, tracking number, SKU, or warehouse" class="mt-2" @keyup.enter="runScan" /><Button label="Search record" variant="solid" theme="green" class="mt-3 w-full" :loading="scanner.loading" @click="runScan" /></div>
              <div><p class="mb-2 text-sm-semibold">Recent searches</p><div class="divide-y divide-outline-gray-1 rounded-4 border border-outline-gray-2"><Button v-for="item in [data.receive.package.tracking, data.receive.asn.reference, data.pick.bin, inventory.items[0]?.item_code].filter(Boolean)" :key="item" :label="item" icon-left="lucide-history" variant="ghost" theme="gray" class="w-full !justify-start" @click="scanValue = item; runScan()" /></div></div>
            </section>

            <section v-else-if="screen === 'receive'" class="space-y-4">
              <template v-if="receiveStored || receiveMode === 'stored'">
                <Button label="Back to packages" icon-left="lucide-arrow-left" variant="ghost" theme="gray" size="sm" class="!px-0" @click="receiveMode = 'tasks'" />
                <div class="wms-stepper"><span class="is-complete">Count</span><span class="is-complete">Stage</span><span class="is-complete">Finish</span></div>
                <Alert title="Stored - inventory available" :description="`${receiveStoredLines.length} line${receiveStoredLines.length === 1 ? '' : 's'}, ${receiveStoredLines.reduce((t, l) => t + Number(l.qty || 0), 0)} units now in their bins.`" theme="green" />
                <div class="rounded-4 border border-outline-gray-2">
                  <div v-for="line in receiveStoredLines" :key="line.item_code" class="flex items-center justify-between gap-2 border-b border-outline-gray-1 p-3 last:border-0">
                    <div class="min-w-0"><p class="truncate text-sm-semibold">{{ line.name || line.item_code }}</p><p class="truncate text-2xs text-ink-gray-5">{{ line.item_code }}</p></div>
                    <div class="text-right"><p class="text-sm-semibold">{{ line.qty }}</p><p class="text-2xs text-ink-gray-5">{{ shortBin(line.bin) }}</p></div>
                  </div>
                </div>
                <Button v-if="receiveStoredEntry" :label="`Stock Entry ${receiveStoredEntry}`" variant="ghost" theme="green" class="w-full" @click="openDesk(data.receive.package.stock_entry_route || '/desk/stock-entry/' + receiveStoredEntry)" />
                <Button label="Receive next package (same client)" variant="solid" theme="green" class="w-full" @click="receiveNextSameClient" />
                <Button label="Back to packages" variant="outline" theme="gray" class="w-full" @click="receiveMode = 'tasks'" />
              </template>

              <template v-else-if="receiveMode === 'finish'">
                <Button label="Back to count and stage" icon-left="lucide-arrow-left" variant="ghost" theme="gray" size="sm" class="!px-0" @click="receiveMode = 'work'" />
                <div class="wms-stepper"><span class="is-complete">Count</span><span class="is-complete">Stage</span><span class="is-active">Finish</span></div>
                <div class="rounded-4 border border-outline-gray-2 p-3">
                  <p class="text-sm-semibold">Ready to store</p>
                  <div class="mt-2 grid grid-cols-3 gap-2 text-center">
                    <div><p class="text-lg-semibold">{{ receiveLines.length }}</p><p class="text-2xs text-ink-gray-5">lines</p></div>
                    <div><p class="text-lg-semibold">{{ receiveUnits }}</p><p class="text-2xs text-ink-gray-5">units</p></div>
                    <div><p class="text-lg-semibold">{{ new Set(receiveLines.map((l) => l.assigned_bin)).size }}</p><p class="text-2xs text-ink-gray-5">bins</p></div>
                  </div>
                  <p v-if="receiveLines.some((l) => ['Damaged', 'Hold'].includes(l.status))" class="mt-2 text-xs text-ink-amber-6">{{ receiveLines.filter((l) => ['Damaged', 'Hold'].includes(l.status)).length }} line(s) damaged or on hold.</p>
                  <p v-if="receiveLines.some((l) => l.needs_review)" class="mt-1 text-xs text-ink-amber-6">{{ receiveLines.filter((l) => l.needs_review).length }} item(s) flagged for Soy Ops review - they store normally.</p>
                </div>
                <div class="rounded-4 border border-outline-gray-2">
                  <div v-for="line in receiveLines" :key="line.sku" class="flex items-center justify-between gap-2 border-b border-outline-gray-1 p-3 last:border-0">
                    <div class="min-w-0"><p class="truncate text-sm-semibold">{{ line.name }}</p><p class="truncate text-2xs text-ink-gray-5">{{ line.sku }}</p></div>
                    <div class="text-right"><p class="text-sm-semibold">{{ line.received }}</p><p class="text-2xs text-ink-gray-5">{{ shortBin(line.assigned_bin) }}</p></div>
                  </div>
                </div>
                <p class="text-xs text-ink-gray-5">Storing posts one stock receipt for the whole package. After this, corrections are made from Live inventory (Adjust qty, Move bin).</p>
                <Button label="Store package" variant="solid" theme="green" class="w-full" :loading="pickActionLoading" :disabled="pickMutationLoading" @click="storeReceivePackage" />
              </template>

              <template v-else>
                <Button label="Back to packages" icon-left="lucide-arrow-left" variant="ghost" theme="gray" size="sm" class="!px-0" @click="receiveMode = 'tasks'" />
                <div class="wms-stepper"><span :class="receiveLines.length ? 'is-complete' : 'is-active'">Count</span><span :class="!receiveLines.length ? '' : (receiveStageableRows.length ? 'is-active' : 'is-complete')">Stage</span><span>Finish</span></div>
                <div class="rounded-4 border border-outline-gray-2 bg-surface-base p-3">
                  <div class="flex items-start justify-between gap-2">
                    <div class="min-w-0"><p class="text-2xs text-ink-gray-5">Receiving for</p><p class="truncate text-base-semibold">{{ data.receive.package.customer || 'No client' }}</p></div>
                    <div class="text-right"><p class="text-2xs text-ink-gray-5">{{ data.receive.package.name }}</p><p v-if="data.receive.package.tracking" class="truncate text-2xs text-ink-gray-5">{{ data.receive.package.tracking }}</p></div>
                  </div>
                  <p class="mt-2 text-xs text-ink-gray-5">{{ receiveLines.length }} line{{ receiveLines.length === 1 ? '' : 's' }} - {{ receiveUnits }} unit{{ receiveUnits === 1 ? '' : 's' }} - {{ receiveLines.length - receiveStageableRows.length }} staged</p>
                </div>

                <div class="rounded-4 border border-outline-green-3 bg-surface-green-1 p-3">
                  <div class="flex items-end gap-2">
                    <TextInput v-model="receiveScanValue" label="Scan or enter barcode" class="flex-1" @keyup.enter="scanReceiveItem">
                      <template #suffix><button type="button" class="lucide-scan-line mr-2 size-4 text-ink-gray-5" aria-label="Scan with camera" @click="openScanner('receive-sku')" /></template>
                    </TextInput>
                    <TextInput v-model="receiveScanQty" type="number" label="Qty" class="w-20" />
                  </div>
                  <Button label="Add" variant="solid" theme="green" class="mt-3 w-full" :loading="pickActionLoading" :disabled="pickMutationLoading" @click="scanReceiveItem" />
                </div>

                <div v-if="newItem" class="space-y-2 rounded-4 border border-outline-amber-2 bg-surface-amber-1 p-3">
                  <div class="flex items-center justify-between gap-2">
                    <p class="text-sm-semibold">New item <span class="text-ink-gray-5">{{ newItem.code }}</span></p>
                    <Badge :label="newItem.barcode_type" theme="gray" variant="subtle" />
                  </div>
                  <p class="text-2xs text-ink-gray-5">{{ newItem.related ? `Filled in from ${newItem.related} - check and confirm.` : 'Not in the catalogue. Pick what it is; anything left blank is flagged for review.' }}</p>
                  <label class="block">
                    <span class="mb-1 block text-2xs text-ink-gray-5">Product</span>
                    <select v-if="!newItem.productNew" :value="newItem.product" class="w-full rounded-4 border border-outline-gray-2 bg-surface-base p-2 text-sm" @change="newItemProductChosen($event.target.value)">
                      <option value="" disabled>Choose product</option>
                      <option v-for="p in newItem.options.products" :key="p.product" :value="p.product">{{ p.product }}</option>
                      <option value="__new__">+ New product...</option>
                    </select>
                    <TextInput v-else v-model="newItem.product" placeholder="e.g. Basic Logo Tee" />
                  </label>
                  <div class="grid grid-cols-2 gap-2">
                    <label class="block">
                      <span class="mb-1 block text-2xs text-ink-gray-5">Color</span>
                      <select v-if="!newItem.colorNew" :value="newItem.color" class="w-full rounded-4 border border-outline-gray-2 bg-surface-base p-2 text-sm" @change="$event.target.value === '__new__' ? (newItem.colorNew = true, newItem.color = '') : (newItem.color = $event.target.value)">
                        <option value="">-</option>
                        <option v-for="c in newItemColors" :key="c" :value="c">{{ c }}</option>
                        <option value="__new__">+ New color...</option>
                      </select>
                      <TextInput v-else v-model="newItem.color" placeholder="e.g. Green" />
                    </label>
                    <label class="block">
                      <span class="mb-1 block text-2xs text-ink-gray-5">Size</span>
                      <select v-if="!newItem.sizeNew" :value="newItem.size" class="w-full rounded-4 border border-outline-gray-2 bg-surface-base p-2 text-sm" @change="$event.target.value === '__new__' ? (newItem.sizeNew = true, newItem.size = '') : (newItem.size = $event.target.value)">
                        <option value="">-</option>
                        <option v-for="z in newItemSizes" :key="z" :value="z">{{ z }}</option>
                        <option value="__new__">+ New size...</option>
                      </select>
                      <TextInput v-else v-model="newItem.size" placeholder="e.g. 3XL" />
                    </label>
                  </div>
                  <div class="grid grid-cols-2 gap-2">
                    <label class="block">
                      <span class="mb-1 block text-2xs text-ink-gray-5">Type</span>
                      <select v-model="newItem.group" class="w-full rounded-4 border border-outline-gray-2 bg-surface-base p-2 text-sm">
                        <option value="">Not sure</option>
                        <option v-for="g in newItem.options.groups" :key="g" :value="g">{{ groupLabel(g) }}</option>
                      </select>
                    </label>
                    <TextInput v-model="newItem.collection" label="Collection" />
                  </div>
                  <div class="rounded-4 border border-outline-gray-2 bg-surface-base p-2">
                    <p class="text-2xs text-ink-gray-5">Item name</p>
                    <p class="text-sm-semibold">{{ newItemName || '-' }}</p>
                  </div>
                  <TextInput v-model="newItem.qty" type="number" label="Quantity" />
                  <label class="flex items-center gap-2 text-xs"><input v-model="newItem.flag" type="checkbox" /> Flag for review</label>
                  <TextInput v-if="newItem.flag" v-model="newItem.note" label="What should Soy Ops check?" />
                  <div class="grid grid-cols-2 gap-2">
                    <Button label="Cancel" variant="outline" theme="gray" @click="newItem = null" />
                    <Button label="Create and add" variant="solid" theme="green" :loading="newItem.busy" @click="submitNewItem" />
                  </div>
                </div>

                <div class="flex items-center justify-between">
                  <p class="text-sm-semibold">In this package</p>
                  <Button v-if="receiveStageableRows.some((l) => stagingBinInputs[l.sku])" label="Stage all to suggested bins" variant="ghost" theme="green" size="sm" :loading="pickActionLoading" @click="stageAllSuggested" />
                </div>
                <div class="rounded-4 border border-outline-gray-2">
                  <div v-for="item in receiveLines" :key="item.sku" class="space-y-2 border-b border-outline-gray-1 p-3 last:border-0">
                    <div class="flex items-center gap-2">
                      <div class="wms-item-thumb shrink-0"><img v-if="item.image" :src="item.image" :alt="item.name" /><span v-else class="lucide-shirt size-5 text-ink-green-6" aria-hidden="true" /></div>
                      <div class="min-w-0 flex-1">
                        <div class="flex items-center gap-1.5">
                          <p class="truncate text-sm-semibold">{{ item.name }}</p>
                          <Badge v-if="item.needs_review" label="Review" theme="orange" variant="subtle" />
                          <Badge v-if="['Damaged', 'Hold'].includes(item.status)" :label="item.status" theme="red" variant="subtle" />
                        </div>
                        <p class="truncate text-2xs text-ink-gray-5">{{ item.sku }}<template v-if="Number(item.quantity) > 0"> - expected {{ item.quantity }}</template></p>
                      </div>
                      <input v-if="!item.assigned_bin" :value="item.received" type="number" min="0" inputmode="numeric" class="w-16 rounded-4 border border-outline-gray-2 bg-surface-base p-1.5 text-center text-sm" :aria-label="`Quantity of ${item.sku}`" @change="setLineQty(item, $event.target.value)" />
                      <p v-else class="w-16 text-center text-sm-semibold">{{ item.received }}</p>
                      <Button icon="lucide-ellipsis-vertical" aria-label="Line options" variant="ghost" theme="gray" size="sm" @click="openLineMenu(item)" />
                    </div>
                    <Badge v-if="item.assigned_bin" :label="`Staged - ${shortBin(item.assigned_bin)}`" theme="green" variant="subtle" />
                    <div v-else class="flex items-center gap-2">
                      <select :value="stagingBinInputs[item.sku] || ''" class="min-w-0 flex-1 rounded-4 border border-outline-gray-2 bg-surface-base p-2 text-sm" @change="stagingBinInputs[item.sku] = $event.target.value; stageBinChosen(item, $event.target.value)">
                        <option value="" disabled>Choose bin</option>
                        <optgroup v-if="binGroups(stageBins, item.sku).held.length" label="Already holds this item">
                          <option v-for="b in binGroups(stageBins, item.sku).held" :key="b.warehouse" :value="b.warehouse">{{ b.code }} - {{ b.held[item.sku] }} here</option>
                        </optgroup>
                        <optgroup label="Other bins">
                          <option v-for="b in binGroups(stageBins, item.sku).other" :key="b.warehouse" :value="b.warehouse">{{ b.code }}{{ b.on_hand ? ` - ${b.on_hand} on hand` : ' - empty' }}</option>
                        </optgroup>
                        <option value="__new__">+ New bin...</option>
                      </select>
                      <button type="button" class="lucide-scan-line size-4 shrink-0 text-ink-gray-5" aria-label="Scan bin with camera" @click="openStageScanner(item)" />
                      <Button label="Stage" variant="solid" theme="green" size="sm" :loading="pickActionLoading" :disabled="!stagingBinInputs[item.sku] || pickMutationLoading" @click="stageItem(item, stagingBinInputs[item.sku])" />
                    </div>
                  </div>
                  <p v-if="!receiveLines.length" class="p-4 text-center text-sm text-ink-gray-5">Scan the first item in the box.</p>
                </div>
                <Button label="Finish" variant="solid" theme="green" class="w-full" :disabled="!receiveLines.length || receiveStageableRows.length > 0 || pickMutationLoading" @click="receiveMode = 'finish'" />
                <p v-if="receiveLines.length && receiveStageableRows.length" class="text-center text-2xs text-ink-gray-5">Stage every line into a bin to finish.</p>
              </template>

              <div v-if="lineMenu" class="wms-create-overlay">
                <div class="wms-create-sheet">
                  <div class="flex items-center justify-between border-b border-outline-gray-2 px-3 py-2.5">
                    <p class="truncate text-sm-semibold">{{ lineMenu.item.name }}</p>
                    <Button icon="lucide-x" aria-label="Close" variant="ghost" theme="gray" @click="lineMenu = null" />
                  </div>
                  <div class="space-y-3 overflow-y-auto p-3">
                    <div>
                      <p class="mb-1 text-2xs text-ink-gray-5">Condition</p>
                      <div class="grid grid-cols-3 gap-2">
                        <Button v-for="c in ['Good', 'Damaged', 'Hold']" :key="c" :label="c" :variant="(lineMenu.item.status === c) || (c === 'Good' && !['Damaged', 'Hold'].includes(lineMenu.item.status)) ? 'solid' : 'outline'" :theme="c === 'Good' ? 'green' : 'gray'" size="sm" :disabled="!!lineMenu.item.assigned_bin" @click="lineSetCondition(c)" />
                      </div>
                      <p class="mt-1 text-2xs text-ink-gray-5">Damaged goes to the client's Damaged area when staged.</p>
                    </div>
                    <label class="block">
                      <span class="mb-1 block text-2xs text-ink-gray-5">Type (item group)</span>
                      <select v-model="lineMenu.group" class="w-full rounded-4 border border-outline-gray-2 bg-surface-base p-2 text-sm">
                        <option v-for="g in lineMenu.groups" :key="g" :value="g">{{ groupLabel(g) }}</option>
                      </select>
                    </label>
                    <Button label="Change type and flag for review" variant="outline" theme="green" class="w-full" :disabled="!lineMenu.group || lineMenu.group === lineMenu.item.item_group" @click="lineSetGroup" />
                    <TextInput v-model="lineMenu.reason" label="Something else wrong? (color, size, name)" placeholder="e.g. Label says navy, item is black" />
                    <Button label="Flag for review" variant="outline" theme="gray" class="w-full" @click="lineFlag" />
                    <Button v-if="!lineMenu.item.assigned_bin" label="Remove line" variant="ghost" theme="red" class="w-full" @click="setLineQty(lineMenu.item, 0); lineMenu = null" />
                  </div>
                </div>
              </div>

              <Button v-if="receiveMode !== 'tasks'" label="Open receiving record" variant="ghost" theme="gray" class="w-full" @click="openDesk(data.receive.package.route)" />
            </section>

            <section v-else-if="screen === 'pick'" class="space-y-3">
              <template v-if="pickMode === 'active'">
                <div class="wms-stepper">
                  <span :class="{ 'is-complete': pickLocationConfirmed, 'is-active': !pickLocationConfirmed }">Location</span>
                  <span :class="{ 'is-complete': pickTotal > 0 && pickDone >= pickTotal, 'is-active': pickLocationConfirmed && pickDone < pickTotal }">Picking</span>
                  <span :class="{ 'is-complete': pickComplete, 'is-active': pickTotal > 0 && pickDone >= pickTotal && !pickComplete }">Complete</span>
                </div>
                <div class="rounded-4 border border-outline-gray-2 bg-surface-base p-3">
                  <div class="flex items-start justify-between gap-2">
                    <div class="min-w-0">
                      <p class="truncate text-lg-semibold">{{ pickContext.name || currentTask?.reference || 'Active order' }}</p>
                      <p class="mt-1 truncate text-xs text-ink-gray-5">{{ pickContext.task_customer || pickContext.party_name || currentTask?.customer || 'Customer' }}</p>
                    </div>
                    <div v-if="pickContext.claimed_at" class="shrink-0 rounded-4 bg-surface-green-1 px-2 py-1 text-center">
                      <p class="text-sm-semibold tabular-nums text-ink-green-7">{{ formatElapsed(pickContext.claimed_at) }}</p>
                      <p class="text-2xs text-ink-green-6">elapsed</p>
                    </div>
                  </div>
                  <div class="mt-3 grid grid-cols-2 gap-x-3 gap-y-1.5 text-xs text-ink-gray-5">
                    <span class="truncate">Picker: {{ pickContext.assigned_to?.name || data.operator.name }}</span>
                    <span v-if="pickContext.created" class="truncate">Created: {{ formatDateTime(pickContext.created) }}</span>
                    <span v-if="pickContext.external_reference" class="truncate">{{ pickContext.reference_label || 'PO' }}: {{ pickContext.external_reference }}</span>
                    <span v-if="pickContext.transaction_date" class="truncate">Ordered: {{ pickContext.transaction_date }}</span>
                  </div>
                  <Badge v-if="pickContext.source_integrity?.status === 'mismatch'" :label="pickContext.source_integrity.label" theme="orange" variant="subtle" class="mt-2" />
                </div>
                  <div class="rounded-4 border border-outline-green-3 bg-surface-green-1 p-3">
                    <p class="text-sm-semibold text-ink-green-7">Scan or Enter SKU</p>
                    <div class="mt-3 flex items-end gap-2">
                      <TextInput v-model="pickScanValue" label="Scan item or bin barcode" class="flex-1" @keyup.enter="scanPickItem">
                        <template #suffix><button type="button" class="lucide-scan-line mr-2 size-4 text-ink-gray-5" aria-label="Scan with camera" @click="openScanner('sku')" /></template>
                      </TextInput>
                    </div>
                    <div class="mt-3 grid grid-cols-2 gap-2">
                      <Button label="Confirm scan" variant="solid" theme="green" :loading="pickActionLoading && pickActionTag === 'scan'" :disabled="pickMutationLoading" @click="scanPickItem" />
                      <Button label="Manual / Exceptions" variant="outline" theme="green" :disabled="pickMutationLoading || !selectedPickItem" @click="openPickItemDrawer(selectedPickItem)" />
                    </div>
                  </div>
                  <div class="rounded-4 border border-outline-gray-2 bg-surface-base">
                    <div class="border-b border-outline-gray-1 px-3 py-2">
                      <div class="flex items-center justify-between gap-2">
                        <p class="text-sm-semibold">Pick Route (by location)</p>
                        <span class="text-lg-semibold text-ink-green-6">{{ pickDone }} / {{ pickTotal }}</span>
                      </div>
                    </div>
                    <div v-for="group in pickBinGroups" :key="group.bin" class="border-b border-outline-gray-1 last:border-0">
                      <div class="flex items-center justify-between gap-2 bg-surface-gray-1 px-3 py-2">
                        <div class="flex min-w-0 items-center gap-1.5 text-xs-semibold text-ink-green-7"><span class="lucide-map-pin size-3.5 shrink-0" aria-hidden="true" /><span class="truncate">{{ group.bin }}</span></div>
                        <Button v-if="!binIsConfirmed(group)" label="I'm here" size="sm" variant="solid" theme="green" @click="confirmBinGroup(group.bin)" />
                        <Badge v-else label="Confirmed" theme="green" variant="subtle" />
                      </div>
                      <div
                        v-for="item in group.items"
                        :key="item.sku"
                        class="wms-pick-row flex items-center gap-2 border-b border-outline-gray-1 p-2 last:border-0"
                        :class="[selectedPickSku === item.sku ? 'bg-surface-green-1' : '', item.picked >= item.quantity && item.status !== 'Short' ? 'opacity-50' : '']"
                        @click="openPickItemDrawer(item)"
                      >
                        <span v-if="item.picked >= item.quantity && item.status !== 'Short'" class="lucide-check-circle-2 size-5 shrink-0 text-ink-green-6" aria-hidden="true" />
                        <div v-else class="wms-item-thumb shrink-0"><img v-if="item.image" :src="item.image" :alt="item.name" /><span v-else class="lucide-shirt size-5 text-ink-green-6" aria-hidden="true" /></div>
                        <div class="min-w-0 flex-1">
                          <div class="flex items-center gap-1.5">
                            <p class="truncate text-base-semibold text-ink-gray-9">{{ item.name }}</p>
                            <Badge v-if="item.status === 'Short' || item.exception_reason" :label="item.exception_reason || 'Short'" theme="red" variant="subtle" />
                          </div>
                          <div class="wms-progress mt-1.5" :class="{ 'is-complete': item.picked >= item.quantity, 'is-short': item.status === 'Short' }">
                            <span :style="{ width: (item.quantity ? Math.min(100, (item.picked / item.quantity) * 100) : 0) + '%' }" />
                          </div>
                        </div>
                        <div class="flex items-center gap-1" @click.stop>
                          <Button label="-" variant="outline" theme="gray" size="sm" class="!min-w-8" :loading="pickActionLoading && selectedPickSku === item.sku" :disabled="item.picked <= 0 || pickMutationLoading || !binIsConfirmed(group)" @click="unpickItem(item)" />
                          <p class="min-w-12 text-center text-sm-semibold">{{ item.picked }} / {{ item.quantity }}</p>
                          <Button label="+" variant="outline" theme="green" size="sm" class="!min-w-8" :loading="pickActionLoading && selectedPickSku === item.sku" :disabled="item.disabled || item.picked >= item.quantity || pickMutationLoading || !binIsConfirmed(group)" @click="pickItem(item)" />
                        </div>
                      </div>
                    </div>
                  </div>
                <div class="rounded-4 border border-outline-gray-2 bg-surface-base p-3">
                  <div class="flex items-center justify-between">
                    <p class="text-sm-semibold">Overall progress</p>
                    <span class="text-sm-semibold text-ink-green-6">{{ pickDone }} / {{ pickTotal }}</span>
                  </div>
                  <div class="wms-progress mt-2" :class="{ 'is-complete': pickTotal > 0 && pickDone >= pickTotal }">
                    <span :style="{ width: (pickTotal ? Math.min(100, (pickDone / pickTotal) * 100) : 0) + '%' }" />
                  </div>
                  <p class="mt-2 text-center text-sm text-ink-gray-5">{{ Math.max(pickTotal - pickDone, 0) }} unit(s) still needed</p>
                  <Button label="Mark order complete" variant="solid" :theme="pickDone >= pickTotal && pickTotal ? 'green' : 'gray'" class="mt-2 w-full" :loading="pickActionLoading && pickActionTag === 'complete'" :disabled="pickDone < pickTotal || !pickTotal || pickMutationLoading" @click="completePick" />
                </div>
              </template>

            </section>

            <section v-else-if="screen === 'pack'" class="space-y-4">
              <template v-if="packMode === 'active'">
                <Button label="Back to pack list" icon-left="lucide-arrow-left" variant="ghost" theme="gray" size="sm" class="!px-0" @click="packMode = 'tasks'" />
                <div class="wms-stepper"><span :class="{ 'is-complete': packDone >= packTotal && packTotal, 'is-active': packDone < packTotal }">Verify</span><span :class="{ 'is-complete': packComplete, 'is-active': packDone >= packTotal && !packComplete }">Complete</span></div>

                <template v-if="!packComplete">
                  <div class="rounded-4 border border-outline-gray-2 bg-surface-base p-3">
                    <div class="flex items-start justify-between gap-3">
                      <div class="min-w-0">
                        <p class="truncate text-lg-semibold">{{ packContext.sales_order || packTaskName || 'Pack container' }}</p>
                        <p class="mt-1 truncate text-xs text-ink-gray-5">{{ packContext.task_customer || packContext.party_name || 'Customer' }}</p>
                      </div>
                      <Badge :label="packContext.package_type || 'Carton Box'" theme="green" variant="subtle" />
                    </div>
                    <div class="mt-3 flex items-center gap-3 text-xs text-ink-gray-5">
                      <span class="truncate">Box: {{ packContext.container || 'Not assigned' }}</span>
                      <span class="truncate">Packer: {{ packContext.assigned_to?.name || data.operator.name }}</span>
                    </div>
                  </div>

                  <div class="rounded-4 border border-outline-green-3 bg-surface-green-1 p-3">
                    <p class="text-sm-semibold text-ink-green-7">Verify contents</p>
                    <div class="mt-3 flex items-end gap-2">
                      <TextInput v-model="packScanValue" label="Scan barcode or enter SKU" class="flex-1" @keyup.enter="scanPackItem">
                        <template #suffix><button type="button" class="lucide-scan-line mr-2 size-4 text-ink-gray-5" aria-label="Scan with camera" @click="openScanner('pack-sku')" /></template>
                      </TextInput>
                    </div>
                    <Button label="Confirm scan" variant="solid" theme="green" class="mt-3 w-full" :loading="packItemRequest.loading" :disabled="packMutationLoading" @click="scanPackItem" />
                  </div>

                  <div class="rounded-4 border border-outline-gray-2 bg-surface-base">
                    <div class="flex items-center justify-between border-b border-outline-gray-1 px-3 py-2">
                      <p class="text-sm-semibold">Box contents</p>
                      <span class="text-lg-semibold text-ink-green-6">{{ packDone }} / {{ packTotal }}</span>
                    </div>
                    <div v-for="item in data.pack.items" :key="item.sku" class="flex items-center gap-2 border-b border-outline-gray-1 p-2 last:border-0">
                      <div class="wms-item-thumb shrink-0"><img v-if="item.image" :src="item.image" :alt="item.name" /><span v-else class="lucide-shirt size-5 text-ink-green-6" aria-hidden="true" /></div>
                      <div class="min-w-0 flex-1">
                        <p class="truncate text-base-semibold text-ink-gray-9">{{ item.name }}</p>
                        <p class="truncate text-xs text-ink-gray-5">{{ item.sku }}</p>
                        <div class="wms-progress mt-1.5" :class="{ 'is-complete': item.packed >= item.quantity }">
                          <span :style="{ width: (item.quantity ? Math.min(100, (item.packed / item.quantity) * 100) : 0) + '%' }" />
                        </div>
                      </div>
                      <div class="flex items-center gap-1">
                        <Button label="-" variant="outline" theme="gray" size="sm" class="!min-w-8" :loading="packMutationLoading" :disabled="item.packed <= 0 || packMutationLoading" @click="unpackItem(item)" />
                        <p class="min-w-12 text-center text-sm-semibold">{{ item.packed }} / {{ item.quantity }}</p>
                        <Button label="+" variant="outline" theme="green" size="sm" class="!min-w-8" :loading="packItemRequest.loading" :disabled="item.disabled || item.packed >= item.picked || packMutationLoading" @click="packItem(item)" />
                      </div>
                    </div>
                  </div>

                  <div class="rounded-4 border border-outline-gray-2 bg-surface-base p-3">
                    <p class="mt-1 text-center text-sm text-ink-gray-5">{{ Math.max(packTotal - packDone, 0) }} unit(s) still to verify</p>
                    <Button label="Pack all picked items" variant="outline" theme="green" class="mt-2 w-full" :loading="packAllRequest.loading" :disabled="packDone >= packTotal || packMutationLoading" @click="packAll" />
                    <Button label="Confirm box &amp; send to shipping" variant="solid" :theme="packDone >= packTotal && packTotal ? 'green' : 'gray'" class="mt-2 w-full" :loading="completePackRequest.loading" :disabled="packDone < packTotal || !packTotal || packMutationLoading" @click="completePack" />
                  </div>
                </template>

                <template v-else>
                  <Alert title="Pack complete" :description="`${packContext.container || 'Container'} is sealed and released to shipping.`" theme="green" />
                  <Button label="Continue to shipping" variant="solid" theme="green" class="w-full" @click="goToShipmentOrder" />
                </template>

                <Button label="Open in Desk" variant="ghost" theme="gray" class="w-full" @click="openDesk(data.pack.task?.route)" />
              </template>

            </section>

            <section v-else-if="screen === 'ship'" class="space-y-4">
              <template v-if="shipMode === 'completed-detail'">
                <Button label="Back to My Tasks" icon-left="lucide-arrow-left" variant="ghost" theme="gray" size="sm" class="!px-0" @click="shipMode = 'tasks'" />
                <div class="rounded-4 border border-outline-gray-2 bg-surface-base p-3">
                  <div class="flex items-start justify-between gap-3">
                    <div class="min-w-0">
                      <p class="truncate text-lg-semibold">{{ data.ship.reference }}</p>
                      <p class="mt-1 truncate text-xs text-ink-gray-5">{{ data.ship.customer }}</p>
                    </div>
                    <Badge :label="data.ship.status" theme="green" variant="subtle" />
                  </div>
                  <div class="mt-3 grid grid-cols-2 gap-x-3 gap-y-2 border-t border-outline-gray-2 pt-3 text-xs">
                    <div><p class="text-ink-gray-5">Carrier</p><p class="mt-1 truncate text-sm-semibold">{{ data.ship.carrier || 'Not set' }}</p></div>
                    <div><p class="text-ink-gray-5">Tracking</p><p class="mt-1 truncate text-sm-semibold">{{ data.ship.tracking_number || 'Not set' }}</p></div>
                    <div><p class="text-ink-gray-5">Container</p><p class="mt-1 truncate text-sm-semibold">{{ shipChain.container || 'Not set' }}</p></div>
                    <div><p class="text-ink-gray-5">Shipment</p><p class="mt-1 truncate text-sm-semibold">{{ data.ship.name }}</p></div>
                  </div>
                </div>

                <div class="rounded-4 border border-outline-gray-2 bg-surface-base p-3">
                  <div class="flex items-center justify-between">
                    <p class="text-sm-semibold">History</p>
                    <Badge :label="shipChain.order_type || 'Unknown'" :theme="shipChain.order_type === 'Online order' ? 'green' : 'orange'" variant="subtle" />
                  </div>
                  <div class="mt-3 space-y-3">
                    <div v-for="(event, index) in (shipChain.history || [])" :key="index" class="flex gap-2">
                      <div class="flex flex-col items-center">
                        <span class="mt-1 size-2 shrink-0 rounded-full bg-ink-green-6" aria-hidden="true" />
                        <span v-if="index < (shipChain.history || []).length - 1" class="mt-1 w-px flex-1 bg-outline-gray-2" aria-hidden="true" />
                      </div>
                      <div class="min-w-0 flex-1 pb-1">
                        <div class="flex items-baseline justify-between gap-2">
                          <p class="truncate text-sm-semibold">{{ event.label }}</p>
                          <span class="shrink-0 text-2xs text-ink-gray-5">{{ event.at }}</span>
                        </div>
                        <p class="truncate text-xs text-ink-gray-5">{{ event.actor }}<span v-if="event.note"> - {{ event.note }}</span></p>
                      </div>
                    </div>
                  </div>
                  <div class="mt-3 grid grid-cols-2 gap-2 border-t border-outline-gray-1 pt-3">
                    <Button v-if="shipChain.pick_route" label="Open Pick Task" variant="ghost" theme="green" size="sm" @click="openDesk(shipChain.pick_route)" />
                    <Button v-if="shipChain.pack_route" label="Open Pack Task" variant="ghost" theme="green" size="sm" @click="openDesk(shipChain.pack_route)" />
                  </div>
                </div>

                <div class="rounded-4 border border-outline-gray-2 bg-surface-base p-3">
                  <p class="text-sm-semibold">Contents</p>
                  <div class="mt-2 rounded-4 border border-outline-gray-2">
                    <div v-for="item in data.ship.items" :key="item.sku" class="border-b border-outline-gray-1 p-2 last:border-0">
                      <div class="flex items-center gap-2">
                        <div class="wms-item-thumb shrink-0"><img v-if="item.image" :src="item.image" :alt="item.name" /><span v-else class="lucide-shirt size-5 text-ink-green-6" aria-hidden="true" /></div>
                        <div class="min-w-0 flex-1">
                          <p class="truncate text-sm-semibold">{{ item.name }}</p>
                          <p class="truncate text-2xs text-ink-gray-5">{{ item.sku }}</p>
                        </div>
                        <p class="shrink-0 text-sm-semibold">{{ item.shipped }} / {{ item.quantity }}</p>
                      </div>
                      <div v-if="item.pick_exception || item.short_qty" class="mt-1.5 flex flex-wrap items-center gap-1.5">
                        <Badge v-if="item.pick_exception" :label="item.pick_exception" theme="red" variant="subtle" />
                        <Badge v-if="item.short_qty" :label="`Short ${item.short_qty}`" theme="orange" variant="subtle" />
                      </div>
                    </div>
                  </div>
                </div>
                <Button label="Open shipment task" variant="ghost" theme="gray" class="w-full" @click="openDesk(data.ship.route)" />
              </template>

              <template v-else>
                <Button label="Back to shipments" icon-left="lucide-arrow-left" variant="ghost" theme="gray" size="sm" class="!px-0" @click="shipMode = 'tasks'" />
                <div class="wms-stepper"><span class="is-complete">Shipment</span><span :class="{ 'is-complete': data.ship.tracking_number, 'is-active': !data.ship.tracking_number }">Label</span><span :class="{ 'is-complete': shipShipped, 'is-active': data.ship.tracking_number && !shipShipped }">Shipped</span></div>
                <div class="rounded-4 border border-outline-green-3 bg-surface-green-1 p-3">
                  <p class="text-2xs-semibold text-ink-green-6">Staged for shipping</p>
                  <p class="mt-1 truncate text-xl-semibold text-ink-green-7">{{ data.ship.reference }}</p>
                  <div class="mt-3 grid grid-cols-2 gap-x-3 gap-y-2 border-t border-outline-green-2 pt-3 text-xs">
                    <div><p class="text-ink-gray-5">Client</p><p class="mt-1 truncate text-sm-semibold">{{ data.ship.customer || 'Not set' }}</p></div>
                    <div><p class="text-ink-gray-5">Carrier</p><p class="mt-1 truncate text-sm-semibold">{{ data.ship.carrier || 'Not set' }}</p></div>
                    <div><p class="text-ink-gray-5">Container</p><p class="mt-1 truncate text-sm-semibold">{{ shipChain.container || 'Not set' }}</p></div>
                    <div><p class="text-ink-gray-5">Packed by</p><p class="mt-1 truncate text-sm-semibold">{{ shipChain.packed_by?.name || 'Unassigned' }}</p></div>
                  </div>
                </div>
                <div class="rounded-4 border border-outline-gray-2 bg-surface-base">
                  <div class="flex items-center justify-between border-b border-outline-gray-1 px-3 py-2">
                    <p class="text-sm-semibold">Contents</p>
                    <span class="text-xs text-ink-green-6">{{ shipPacked }} / {{ shipTotal }} packed</span>
                  </div>
                  <div v-for="item in data.ship.items" :key="item.sku" class="flex items-center gap-2 border-b border-outline-gray-1 p-2 last:border-0">
                    <div class="wms-item-thumb shrink-0"><img v-if="item.image" :src="item.image" :alt="item.name" /><span v-else class="lucide-shirt size-5 text-ink-green-6" aria-hidden="true" /></div>
                    <div class="min-w-0 flex-1"><p class="truncate text-sm-semibold">{{ item.name }}</p><p class="truncate text-2xs text-ink-gray-5">{{ item.sku }}</p></div>
                    <p class="text-sm-semibold">{{ item.packed }} / {{ item.quantity }}</p>
                  </div>
                </div>
                <div v-if="!data.ship.tracking_number" class="rounded-4 border border-outline-gray-2 bg-surface-base p-3">
                  <div class="flex items-center justify-between"><p class="text-sm-semibold">Ship to</p><span v-if="data.ship.ship_to_source === 'order'" class="text-2xs text-ink-green-6">Prefilled from the order</span></div>
                  <div class="mt-2 grid grid-cols-2 gap-2">
                    <TextInput v-for="[key, label] in shipToFields" :key="key" v-model="shipForm[key]" :label="label" :class="['name', 'company', 'line_1', 'line_2', 'phone', 'email'].includes(key) ? 'col-span-2' : ''" />
                  </div>
                  <p class="mt-3 text-sm-semibold">Parcel</p>
                  <div class="mt-2 grid grid-cols-2 gap-2">
                    <TextInput v-for="[key, label] in parcelFields" :key="key" v-model="shipForm[key]" :label="label" type="number" />
                  </div>
                </div>
                <Button v-if="!data.ship.tracking_number" label="Generate shipping label" variant="solid" theme="green" class="w-full" :loading="pickActionLoading" :disabled="pickMutationLoading" @click="generateLabel" />
                <div v-else class="rounded-4 border border-outline-gray-2 p-3"><p class="text-2xs text-ink-gray-5">Shipping label</p><p class="mt-1 text-lg-semibold">{{ data.ship.tracking_number }}</p><p class="mt-1 text-xs text-ink-gray-5">{{ data.ship.carrier || 'Carrier' }} - {{ data.ship.name }}</p><a v-if="data.ship.label_url" :href="data.ship.label_url" target="_blank" rel="noopener" class="mt-2 inline-block text-xs text-ink-green-6 underline">View / print label</a></div>
                <Button v-if="data.ship.tracking_number" label="Mark shipment shipped" variant="solid" theme="green" class="w-full" :loading="pickActionLoading" :disabled="pickMutationLoading" @click="completeShipment" />
                <Button label="Open shipment task" variant="ghost" theme="gray" class="w-full" @click="openDesk(data.ship.route)" />
              </template>
            </section>

            <section v-else-if="screen === 'inventory'" class="space-y-4">
              <div v-if="selectedInventoryItem" class="space-y-4">
                <Button label="Back to inventory" icon-left="lucide-arrow-left" variant="ghost" theme="gray" @click="selectedItemCode = ''" />
                <div class="flex items-center gap-3">
                  <div class="wms-item-thumb shrink-0"><img v-if="selectedInventoryItem.image" :src="selectedInventoryItem.image" :alt="selectedInventoryItem.item_name" /><span v-else class="lucide-shirt size-5 text-ink-green-6" aria-hidden="true" /></div>
                  <div class="min-w-0"><p class="truncate text-xl-semibold">{{ selectedInventoryItem.item_name }}</p><p class="mt-1 truncate text-xs text-ink-gray-5">{{ selectedInventoryItem.item_code }} - {{ selectedInventoryItem.uom }}</p></div>
                </div>
                <div class="grid grid-cols-3 divide-x divide-outline-gray-2 rounded-4 border border-outline-gray-2 py-3 text-center"><div><p class="text-lg-semibold">{{ formatQty(selectedInventoryItem.on_hand) }}</p><p class="text-2xs text-ink-gray-5">On hand</p></div><div><p class="text-lg-semibold">{{ formatQty(selectedInventoryItem.reserved) }}</p><p class="text-2xs text-ink-gray-5">Reserved</p></div><div><p class="text-lg-semibold">{{ formatQty(selectedInventoryItem.available) }}</p><p class="text-2xs text-ink-gray-5">Available</p></div></div>

                <div class="grid grid-cols-2 gap-2 rounded-4 border border-outline-gray-2 bg-surface-base p-1">
                  <Button label="Locations" :variant="itemDetailTab === 'locations' ? 'solid' : 'ghost'" theme="green" @click="itemDetailTab = 'locations'" />
                  <Button label="Activity" :variant="itemDetailTab === 'activity' ? 'solid' : 'ghost'" theme="green" @click="itemDetailTab = 'activity'" />
                </div>

                <div v-if="itemDetailTab === 'locations'">
                  <Alert v-if="!selectedInventoryItem.locations.length" title="No bin assigned" description="This stock item has no ERPNext Bin record yet." theme="amber" />
                  <div v-for="location in selectedInventoryItem.locations" :key="location.warehouse" class="mb-2 rounded-4 border border-outline-gray-2 p-3">
                    <div class="flex items-center justify-between"><p class="text-sm-semibold">{{ location.warehouse }}</p><Badge :label="`${formatQty(location.available)} available`" :theme="location.available < 0 ? 'red' : 'green'" variant="subtle" /></div>
                    <p class="mt-2 text-xs text-ink-gray-5">On hand {{ formatQty(location.on_hand) }} - Reserved {{ formatQty(location.reserved) }} - Projected {{ formatQty(location.projected) }}</p>
                    <div class="mt-3 grid grid-cols-2 gap-2">
                      <Button label="Adjust qty" size="sm" variant="outline" theme="gray" @click="openBinAction(location, 'adjust')" />
                      <Button label="Move bin" size="sm" variant="outline" theme="gray" @click="openBinAction(location, 'move')" />
                    </div>
                  </div>
                </div>
                <div v-else>
                  <LoadingText v-if="binActivityLoading" text="Loading activity" />
                  <p v-else-if="!binActivity.length" class="py-3 text-center text-xs text-ink-gray-5">No recorded movements for this item yet.</p>
                  <div v-else class="divide-y divide-outline-gray-1 rounded-4 border border-outline-gray-2">
                    <button v-for="entry in binActivity" :key="entry.source_name + entry.warehouse + entry.timestamp" type="button" class="block w-full p-3 text-left" @click="openActivityEntry(entry)">
                      <div class="flex items-center justify-between gap-2"><p class="truncate text-xs-semibold">{{ entry.warehouse }}</p><Badge :label="`${entry.quantity_change > 0 ? '+' : ''}${formatQty(entry.quantity_change)}`" :theme="entry.quantity_change < 0 ? 'orange' : 'green'" variant="subtle" /></div>
                      <p class="mt-1 text-2xs text-ink-gray-5">{{ formatQty(entry.previous_qty) }} → {{ formatQty(entry.new_qty) }} · {{ entry.reason }}<template v-if="entry.source_name"> · {{ entry.source_type }} {{ entry.source_name }}</template></p>
                      <p class="mt-1 text-2xs text-ink-gray-4">{{ entry.user }} · {{ entry.timestamp }}</p>
                      <p v-if="entry.notes" class="mt-1 text-2xs italic text-ink-gray-5">{{ entry.notes }}</p>
                    </button>
                  </div>
                </div>

                <Button label="Open item in ERPNext" variant="ghost" theme="gray" class="w-full" @click="openDesk(selectedInventoryItem.route)" />
              </div>
              <template v-else>
                <div class="grid grid-cols-3 gap-2 rounded-4 border border-outline-gray-2 bg-surface-base p-1">
                  <Button :label="inventory.summary.stocked_bin_count ? `Bins (${inventory.summary.stocked_bin_count})` : 'Bins'" :variant="inventoryView === 'staged' ? 'solid' : 'ghost'" theme="green" @click="inventoryView = 'staged'" />
                  <Button :label="inventory.summary.sku_count ? `Items (${inventory.summary.sku_count})` : 'Items'" :variant="inventoryView === 'items' ? 'solid' : 'ghost'" theme="gray" @click="inventoryView = 'items'" />
                  <Button :label="globalActivity.length ? `History (${globalActivity.length})` : 'History'" :variant="inventoryView === 'history' ? 'solid' : 'ghost'" theme="gray" @click="inventoryView = 'history'; loadGlobalActivity()" />
                </div>
                <TextInput v-if="inventoryView !== 'history'" v-model="inventoryQuery" :label="inventoryView === 'staged' ? 'Search bin or item' : 'Search item, SKU, or location'" />
                <div v-if="inventoryView !== 'history' && (traitOptions.company.length || traitOptions.color.length || traitOptions.size.length)" class="space-y-2">
                  <button type="button" class="flex w-full items-center justify-between rounded-4 border border-outline-gray-2 bg-surface-base px-3 py-1.5 text-xs" :aria-expanded="filtersOpen" @click="filtersOpen = !filtersOpen">
                    <span class="flex items-center gap-1.5"><span class="lucide-sliders-horizontal size-3.5 text-ink-gray-5" aria-hidden="true" />Filters<Badge v-if="activeFilterCount" :label="String(activeFilterCount)" theme="green" variant="subtle" /></span>
                    <span :class="filtersOpen ? 'lucide-chevron-up' : 'lucide-chevron-down'" class="size-4 text-ink-gray-4" aria-hidden="true" />
                  </button>
                  <div v-if="filtersOpen" class="grid grid-cols-3 gap-2">
                    <select v-for="key in ['company', 'color', 'size']" :key="key" v-model="traitFilter[key]" class="min-w-0 rounded-4 border border-outline-gray-2 bg-surface-base p-1.5 text-xs" :aria-label="`Filter by ${FILTER_LABELS[key].toLowerCase()}`">
                      <option value="">{{ FILTER_LABELS[key] }}</option>
                      <option v-for="value in traitOptions[key]" :key="value" :value="value">{{ value }}</option>
                    </select>
                  </div>
                </div>
                <Button v-if="inventoryView === 'staged'" label="+ New bin" variant="outline" theme="green" class="w-full" @click="openNewBin(false)" />
                <div v-if="inventoryView === 'history'" class="space-y-3">
                  <LoadingText v-if="globalActivityLoading" text="Loading activity" />
                  <p v-else-if="!globalActivity.length" class="py-8 text-center text-sm text-ink-gray-5">No recorded movements yet.</p>
                  <div v-else class="divide-y divide-outline-gray-1 rounded-4 border border-outline-gray-2">
                    <button v-for="entry in globalActivity" :key="entry.source_name + entry.item_code + entry.warehouse + entry.timestamp" type="button" class="block w-full p-3 text-left" @click="openActivityEntry(entry)">
                      <div class="flex items-center justify-between gap-2"><p class="truncate text-xs-semibold">{{ entry.item_code }} · {{ entry.warehouse }}</p><Badge :label="`${entry.quantity_change > 0 ? '+' : ''}${formatQty(entry.quantity_change)}`" :theme="entry.quantity_change < 0 ? 'orange' : 'green'" variant="subtle" /></div>
                      <p class="mt-1 text-2xs text-ink-gray-5">{{ formatQty(entry.previous_qty) }} → {{ formatQty(entry.new_qty) }} · {{ entry.reason }}<template v-if="entry.source_name"> · {{ entry.source_type }} {{ entry.source_name }}</template></p>
                      <p class="mt-1 text-2xs text-ink-gray-4">{{ entry.user }} · {{ entry.timestamp }}</p>
                    </button>
                  </div>
                </div>
                <div v-else-if="inventoryView === 'staged'" class="space-y-3">
                  <div v-for="bin in stagedBins" :key="bin.name" class="rounded-4 border border-outline-gray-2 bg-surface-base">
                    <div class="flex items-center justify-between gap-2 border-b border-outline-gray-1 px-3 py-2">
                      <div class="flex min-w-0 items-center gap-1.5"><span class="lucide-map-pin size-3.5 shrink-0 text-ink-green-6" aria-hidden="true" /><div class="min-w-0"><p class="truncate text-sm-semibold text-ink-green-7">{{ bin.label }}</p><p class="truncate text-2xs text-ink-gray-5">{{ bin.parent }}</p></div></div>
                      <div class="flex shrink-0 items-center gap-2">
                        <Badge :label="`${formatQty(bin.on_hand)} units`" theme="green" variant="subtle" />
                        <button type="button" aria-label="Open bin in ERPNext" class="lucide-external-link size-3.5 text-ink-gray-4" @click="openDesk(bin.route)" />
                      </div>
                    </div>
                    <button v-for="item in bin.items" :key="item.item_code" type="button" class="flex w-full items-center gap-2 border-b border-outline-gray-1 p-2 text-left last:border-0" @click="selectedItemCode = item.item_code">
                      <div class="wms-item-thumb shrink-0"><img v-if="item.image" :src="item.image" :alt="item.item_name" /><span v-else class="lucide-shirt size-5 text-ink-green-6" aria-hidden="true" /></div>
                      <div class="min-w-0 flex-1"><p class="truncate text-sm-semibold">{{ item.item_name }}</p><p class="truncate text-2xs text-ink-gray-5">{{ item.item_code }}</p></div>
                      <p class="text-sm-semibold">{{ formatQty(item.on_hand) }}</p>
                      <span class="lucide-chevron-right size-4 shrink-0 text-ink-gray-4" aria-hidden="true" />
                    </button>
                    <Button label="Start pick from this bin" variant="ghost" theme="green" size="sm" class="w-full !justify-start border-t border-outline-gray-1" @click="openPickFromBin(bin)" />
                  </div>
                  <p v-if="!stagedBins.length" class="py-8 text-center text-sm text-ink-gray-5">No bins are holding stock yet.</p>
                </div>
                <div v-else class="space-y-3">
                  <div class="grid grid-cols-4 gap-1"><Button v-for="filter in [{ key: 'all', label: 'All' }, { key: 'stock', label: 'In stock' }, { key: 'reserved', label: 'Reserved' }, { key: 'unassigned', label: 'No bin' }]" :key="filter.key" :label="filter.label" :variant="inventoryFilter === filter.key ? 'solid' : 'ghost'" :theme="filter.key === 'all' ? 'green' : 'gray'" size="sm" @click="inventoryFilter = filter.key" /></div>
                  <div class="divide-y divide-outline-gray-1 rounded-4 border border-outline-gray-2"><Button v-for="item in filteredInventory.slice(0, 100)" :key="item.item_code" variant="ghost" theme="gray" class="wms-inventory-row w-full !justify-start" @click="selectedItemCode = item.item_code"><div class="flex w-full items-center gap-3 text-left"><div class="wms-item-thumb shrink-0"><img v-if="item.image" :src="item.image" :alt="item.item_name" /><span v-else class="lucide-shirt size-5 text-ink-green-6" aria-hidden="true" /></div><div class="min-w-0 flex-1"><p class="truncate text-sm-semibold">{{ item.item_name }}</p><p class="mt-1 truncate text-2xs text-ink-gray-5">{{ item.item_code }} - {{ item.primary_location }}</p></div><div class="w-14 text-right"><p class="text-sm-semibold" :class="item.available < 0 ? 'text-ink-red-5' : ''">{{ formatQty(item.available) }}</p><p class="text-2xs text-ink-gray-5">available</p></div><span class="lucide-chevron-right size-4 text-ink-gray-4" aria-hidden="true" /></div></Button></div>
                  <p v-if="!filteredInventory.length" class="py-8 text-center text-sm text-ink-gray-5">No inventory matches this filter.</p>
                  <p v-else-if="filteredInventory.length > 100" class="text-center text-xs text-ink-gray-5">Showing the first 100 matching items.</p>
                </div>
              </template>
            </section>

            <section v-else-if="screen === 'settings'" class="space-y-4"><div class="rounded-4 border border-outline-gray-2 p-3"><p class="text-sm-semibold">User profile</p><div class="mt-3 flex items-center justify-between"><span class="text-sm text-ink-gray-5">Name</span><span class="text-sm-semibold">{{ data.operator.name }}</span></div><div class="mt-2 flex items-center justify-between"><span class="text-sm text-ink-gray-5">Role</span><span class="text-sm-semibold">{{ data.operator.role }}</span></div></div><div class="rounded-4 border border-outline-gray-2"><div class="p-3"><p class="text-sm-semibold">App settings</p></div><div class="flex items-center justify-between border-t border-outline-gray-1 p-3"><span class="text-sm">Vibration</span><Switch v-model="vibration" /></div><div class="flex items-center justify-between border-t border-outline-gray-1 p-3"><span class="text-sm">Sound</span><Switch v-model="sound" /></div></div><div class="grid grid-cols-2 gap-2"><Button label="Test scanner" variant="outline" theme="green" @click="setScreen('search')" /><Button label="Sync status" variant="outline" theme="green" @click="setScreen('sync')" /></div><Button label="Return to Frappe Desk" variant="ghost" theme="gray" class="w-full" @click="openDesk('/desk')" /><div class="rounded-4 border border-outline-gray-2 p-3"><div class="flex items-center justify-between"><span class="text-sm text-ink-gray-5">App version</span><span class="text-sm-semibold">v{{ APP_VERSION }}</span></div><div class="mt-2 flex items-center justify-between"><span class="text-sm text-ink-gray-5">Build</span><span class="text-sm-semibold">{{ APP_BUILD_DATE }}</span></div></div></section>
            <section v-else-if="screen === 'sync'" class="space-y-4"><Alert title="Online" description="ERPNext and the SoyPaq API are available." theme="green" /><div class="divide-y divide-outline-gray-1 rounded-4 border border-outline-gray-2"><div v-for="row in [{ label: 'Last sync', value: lastDemoSync }, { label: 'Pending scans', value: data.sync.pending }, { label: 'Failed uploads', value: 0 }, { label: 'Live inventory SKUs', value: inventory.summary.sku_count }]" :key="row.label" class="flex justify-between p-3"><span class="text-sm text-ink-gray-5">{{ row.label }}</span><span class="text-sm-semibold">{{ row.value }}</span></div></div><Button label="Sync now" variant="solid" theme="green" class="w-full" :loading="bootstrap.loading" @click="refresh('ERPNext data synced')" /><Alert title="Offline capable demo" description="The interface preserves workflow state during this browser session." theme="gray" /></section>
          </template>
        </section>

        <div v-if="startReceiveOpen" class="wms-create-overlay">
          <div class="wms-create-sheet">
            <div class="flex items-center justify-between border-b border-outline-gray-2 px-3 py-2.5">
              <p class="text-sm-semibold">Start receiving</p>
              <Button icon="lucide-x" aria-label="Close" variant="ghost" theme="gray" @click="closeStartReceiving" />
            </div>
            <div class="space-y-3 overflow-y-auto p-3">
              <p class="text-xs text-ink-gray-5">No items yet - just who this box belongs to. Scan what's actually inside once the package is open.</p>
              <label class="block">
                <span class="mb-1 block text-2xs text-ink-gray-5">Client</span>
                <select v-model="startReceiveCustomer" class="w-full rounded-4 border border-outline-gray-2 bg-surface-base p-2 text-sm" :disabled="!!startReceiveNew">
                  <option value="" disabled>Choose client</option>
                  <option v-for="name in startReceiveClients" :key="name" :value="name">{{ name }}</option>
                </select>
              </label>
              <div v-if="startReceiveCanCreate && !startReceiveNew">
                <Button label="+ Create new client" variant="ghost" theme="green" size="sm" @click="startReceiveNew = { name: '', busy: false, setting: '' }" />
              </div>
              <div v-if="startReceiveNew" class="space-y-2 rounded-4 border border-outline-gray-2 bg-surface-gray-1 p-3">
                <p class="text-xs-semibold">New client</p>
                <TextInput v-model="startReceiveNew.name" label="Client name" placeholder="e.g. Acme Co" :disabled="startReceiveNew.busy" />
                <p v-if="startReceiveNew.setting" class="text-xs text-ink-gray-5">Setting up {{ startReceiveNew.setting }} - warehouses and first bin. This takes a few seconds.</p>
                <div class="grid grid-cols-2 gap-2">
                  <Button label="Cancel" variant="outline" theme="gray" :disabled="startReceiveNew.busy" @click="startReceiveNew = null" />
                  <Button label="Create client" variant="solid" theme="green" :loading="startReceiveNew.busy" @click="createStartReceiveClient" />
                </div>
              </div>
              <TextInput v-model="startReceiveTracking" label="Tracking number (optional)" placeholder="Scan or type if the box has one" />
            </div>
            <div class="border-t border-outline-gray-2 p-3">
              <Button label="Start receiving" variant="solid" theme="green" class="w-full" :loading="startReceiveBusy" :disabled="!!startReceiveNew" @click="submitStartReceiving" />
            </div>
          </div>
        </div>

        <div v-if="pickMode === 'drawer'" class="wms-create-overlay">
          <div class="wms-create-sheet">
            <div class="flex items-center justify-between border-b border-outline-gray-2 px-3 py-2.5">
              <p class="truncate text-sm-semibold">{{ selectedPickItem?.name || 'Item' }}</p>
              <Button icon="lucide-x" aria-label="Close" variant="ghost" theme="gray" @click="pickMode = 'active'" />
            </div>
            <div class="space-y-4 overflow-y-auto p-3">
              <div class="flex items-start gap-3">
                <div class="wms-item-thumb !h-16 !w-16 shrink-0"><img v-if="selectedPickItem?.image" :src="selectedPickItem.image" :alt="selectedPickItem.name" /><span v-else class="lucide-shirt size-8 text-ink-green-6" aria-hidden="true" /></div>
                <div class="min-w-0 flex-1">
                  <div class="flex items-start justify-between gap-2">
                    <div class="min-w-0">
                      <p class="mt-0.5 flex items-center gap-1 truncate text-sm-semibold text-ink-green-7"><span class="lucide-map-pin size-3.5" aria-hidden="true" /> {{ selectedPickItem?.source_bin || selectedPickItem?.source_warehouse || 'No location' }}</p>
                      <p class="truncate text-2xs text-ink-gray-5">{{ selectedPickItem?.sku }}</p>
                    </div>
                    <Badge
                      :label="selectedPickItem?.status === 'Short' ? 'Short' : (selectedPickItem && selectedPickItem.picked >= selectedPickItem.quantity ? 'Picked' : 'Pending')"
                      :theme="selectedPickItem?.status === 'Short' ? 'red' : (selectedPickItem && selectedPickItem.picked >= selectedPickItem.quantity ? 'green' : 'orange')"
                      variant="subtle"
                    />
                  </div>
                </div>
              </div>
              <Alert v-if="selectedPickItem?.exception_reason" :title="`Flagged: ${selectedPickItem.exception_reason}`" :description="selectedPickItem?.exception_note || ''" theme="red" />

              <div class="rounded-4 border border-outline-gray-1 p-3">
                <div class="flex items-center justify-between text-xs text-ink-gray-5">
                  <p>Picked / Needed</p>
                  <p>UOM: {{ selectedPickItem?.uom || 'EA' }}</p>
                </div>
                <div class="mt-2 flex items-center justify-center gap-4">
                  <Button label="-" variant="outline" theme="gray" class="!min-w-10" :loading="pickActionLoading" :disabled="!selectedPickItem || selectedPickItem.picked <= 0 || pickMutationLoading" @click="unpickItem(selectedPickItem)" />
                  <p class="min-w-20 text-center text-2xl-semibold">{{ selectedPickItem?.picked || 0 }} / {{ selectedPickItem?.quantity || 0 }}</p>
                  <Button label="+" variant="solid" theme="green" class="!min-w-10" :loading="pickActionLoading" :disabled="!selectedPickItem || selectedPickItem.disabled || selectedPickItem.picked >= selectedPickItem.quantity || pickMutationLoading" @click="pickItem(selectedPickItem)" />
                </div>
              </div>

              <div>
                <p class="mb-2 text-sm-semibold">Report an exception</p>
                <div class="grid grid-cols-2 gap-2">
                  <Button label="Short / Missing" size="sm" :variant="pickExceptionReason === 'Short Picked' ? 'solid' : 'outline'" theme="red" :disabled="pickMutationLoading || !selectedPickItem" @click="selectPickException('Short Picked')" />
                  <Button label="Damaged" size="sm" :variant="pickExceptionReason === 'Damaged' ? 'solid' : 'outline'" theme="gray" :disabled="pickMutationLoading || !selectedPickItem" @click="selectPickException('Damaged')" />
                  <Button label="Wrong Item" size="sm" :variant="pickExceptionReason === 'Wrong Item' ? 'solid' : 'outline'" theme="gray" :disabled="pickMutationLoading || !selectedPickItem" @click="selectPickException('Wrong Item')" />
                  <Button label="No Stock" size="sm" :variant="pickExceptionReason === 'No Stock' ? 'solid' : 'outline'" theme="gray" :disabled="pickMutationLoading || !selectedPickItem" @click="selectPickException('No Stock')" />
                </div>
                <div v-if="pickExceptionReason" class="mt-3 space-y-2 rounded-4 bg-surface-gray-1 p-3">
                  <p class="text-2xs-semibold text-ink-gray-6">{{ pickExceptionReason }} - details</p>
                  <TextInput v-model="pickExceptionNote" label="Note (optional)" placeholder="What happened?" />
                  <div class="flex items-center gap-2">
                    <img v-if="pickExceptionImage" :src="pickExceptionImage" alt="Exception photo" class="size-12 shrink-0 rounded-4 border border-outline-gray-2 object-cover" />
                    <Button :label="pickExceptionImage ? 'Retake photo' : 'Add photo'" icon-left="lucide-camera" variant="outline" theme="gray" size="sm" :loading="pickExceptionUploading" @click="pickPhotoInput?.click()" />
                  </div>
                  <input ref="pickPhotoInput" type="file" accept="image/*" capture="environment" class="hidden" @change="handlePickExceptionPhoto" />
                  <Button label="Save exception" variant="solid" theme="red" class="w-full" :loading="pickActionLoading" :disabled="pickMutationLoading" @click="submitPickException" />
                </div>
                <Button
                  label="Can't scan - confirm manually"
                  variant="outline"
                  theme="green"
                  size="sm"
                  class="mt-2 w-full"
                  :loading="pickActionLoading"
                  :disabled="pickMutationLoading || !selectedPickItem || selectedPickItem.picked >= selectedPickItem.quantity"
                  @click="flagPickItem('Barcode Issue', true)"
                />
              </div>
            </div>
          </div>
        </div>

        <div v-if="activeBinAction.location" class="wms-create-overlay">
          <div class="wms-create-sheet">
            <div class="flex items-center justify-between border-b border-outline-gray-2 px-3 py-2.5">
              <p class="text-sm-semibold">{{ activeBinAction.mode === 'adjust' ? 'Adjust qty' : 'Move bin' }} - {{ activeBinAction.location.warehouse }}</p>
              <Button icon="lucide-x" aria-label="Close" variant="ghost" theme="gray" @click="closeBinAction" />
            </div>
            <div class="space-y-4 overflow-y-auto p-3">
              <p class="text-xs text-ink-gray-5">{{ selectedInventoryItem?.item_name }} · On hand here {{ formatQty(activeBinAction.location.on_hand) }}</p>
              <template v-if="activeBinAction.mode === 'adjust'">
                <div>
                  <p class="mb-2 text-center text-2xs text-ink-gray-5">Correct quantity</p>
                  <div class="flex items-center justify-center gap-3">
                    <Button icon="lucide-minus" aria-label="Decrease by 1" size="lg" variant="outline" theme="gray" @click="binAdjustFinal = String(Math.max(0, Number(binAdjustFinal || 0) - 1))" />
                    <TextInput v-model="binAdjustFinal" type="number" class="w-24 text-center" />
                    <Button icon="lucide-plus" aria-label="Increase by 1" size="lg" variant="outline" theme="gray" @click="binAdjustFinal = String(Number(binAdjustFinal || 0) + 1)" />
                  </div>
                </div>
                <div>
                  <p class="mb-1 text-2xs text-ink-gray-5">Reason</p>
                  <div class="grid grid-cols-3 gap-1">
                    <Button v-for="reason in ['Count Correction', 'Damage', 'Physical Recount']" :key="reason" :label="reason" size="sm" :variant="binAdjustReason === reason ? 'solid' : 'ghost'" theme="gray" @click="binAdjustReason = reason" />
                  </div>
                </div>
                <p v-if="binAdjustFinal !== '' && Number(binAdjustFinal) !== Number(activeBinAction.location.on_hand)" class="text-center text-xs text-ink-gray-5">{{ formatQty(activeBinAction.location.on_hand) }} → {{ formatQty(Number(binAdjustFinal)) }}</p>
              </template>
              <template v-else>
                <div>
                  <p class="mb-2 text-center text-2xs text-ink-gray-5">Quantity to move</p>
                  <div class="flex items-center justify-center gap-3">
                    <Button icon="lucide-minus" aria-label="Decrease by 1" size="lg" variant="outline" theme="gray" @click="binMoveQty = String(Math.max(0, Number(binMoveQty || 0) - 1))" />
                    <TextInput v-model="binMoveQty" type="number" class="w-24 text-center" />
                    <Button icon="lucide-plus" aria-label="Increase by 1" size="lg" variant="outline" theme="gray" @click="binMoveQty = String(Number(binMoveQty || 0) + 1)" />
                  </div>
                </div>
                <label class="block">
                  <span class="mb-1 block text-2xs text-ink-gray-5">Destination bin</span>
                  <select v-model="binMoveTarget" class="w-full rounded-4 border border-outline-gray-2 bg-surface-base p-2 text-sm" @change="moveBinChosen($event.target.value)">
                    <option value="" disabled>Choose bin</option>
                    <optgroup v-if="binGroups(moveBins, selectedInventoryItem?.item_code, activeBinAction.location.warehouse).held.length" label="Already holds this item">
                      <option v-for="b in binGroups(moveBins, selectedInventoryItem?.item_code, activeBinAction.location.warehouse).held" :key="b.warehouse" :value="b.warehouse">{{ b.code }} - {{ b.held[selectedInventoryItem?.item_code] }} here</option>
                    </optgroup>
                    <optgroup label="Other bins">
                      <option v-for="b in binGroups(moveBins, selectedInventoryItem?.item_code, activeBinAction.location.warehouse).other" :key="b.warehouse" :value="b.warehouse">{{ b.code }}{{ b.on_hand ? ` - ${b.on_hand} on hand` : ' - empty' }}</option>
                    </optgroup>
                    <option value="__new__">+ New bin...</option>
                  </select>
                </label>
                <p v-if="binMoveTarget" class="text-xs text-ink-gray-5">{{ shortBin(activeBinAction.location.warehouse) }} → {{ shortBin(binMoveTarget) }}</p>
              </template>
            </div>
            <div class="border-t border-outline-gray-2 p-3">
              <Button v-if="activeBinAction.mode === 'adjust'" label="Apply adjustment" variant="solid" theme="green" class="w-full" :loading="binActionBusy" @click="submitBinAdjust(activeBinAction.location)" />
              <Button v-else label="Move stock" variant="solid" theme="green" class="w-full" :loading="binActionBusy" @click="submitBinMove(activeBinAction.location)" />
            </div>
          </div>
        </div>

        <div v-if="newBin" class="wms-create-overlay wms-fixed">
          <div class="wms-create-sheet">
            <div class="flex items-center justify-between border-b border-outline-gray-2 px-3 py-2.5">
              <p class="text-sm-semibold">New bin</p>
              <Button icon="lucide-x" aria-label="Close" variant="ghost" theme="gray" @click="newBin = null" />
            </div>
            <div class="space-y-3 overflow-y-auto p-3">
              <label class="block">
                <span class="mb-1 block text-2xs text-ink-gray-5">Customer</span>
                <select v-model="newBin.customer" class="w-full rounded-4 border border-outline-gray-2 bg-surface-base p-2 text-sm" @change="newBinCustomerChanged">
                  <option v-for="name in newBin.customers" :key="name" :value="name">{{ name }}</option>
                </select>
              </label>
              <div class="rounded-4 border border-outline-gray-2 bg-surface-gray-1 p-2 text-xs text-ink-gray-5">
                Customer not listed? A customer needs a Company and a Storage zone before it can hold bins.
                <Button label="+ New customer" variant="ghost" theme="green" size="sm" class="mt-1" @click="openDesk('/desk/customer/new')" />
              </div>
              <TextInput v-model="newBin.code" label="Bin code" placeholder="A07" />
              <p class="text-xs text-ink-gray-5">Default is the next free code for this customer. Edit to use another letter or number.</p>
            </div>
            <div class="border-t border-outline-gray-2 p-3">
              <Button label="Create bin" variant="solid" theme="green" class="w-full" :loading="newBin.busy" @click="submitNewBin" />
            </div>
          </div>
        </div>

        <div v-if="pickCompleteConfirmOpen" class="wms-create-overlay">
          <div class="wms-create-sheet">
            <div class="flex items-center justify-between border-b border-outline-gray-2 px-3 py-2.5">
              <p class="text-sm-semibold">Send to packing?</p>
              <Button icon="lucide-x" aria-label="Close" variant="ghost" theme="gray" @click="closePickCompleteConfirm" />
            </div>
            <div class="space-y-3 overflow-y-auto p-3">
              <p class="text-sm text-ink-gray-6">This pick is fully picked. Should it move on to Pack in SoyPaq, or is packing/shipping being handled outside the app for now?</p>
            </div>
            <div class="space-y-2 border-t border-outline-gray-2 p-3">
              <Button label="Send to Pack" variant="solid" theme="green" class="w-full" :loading="pickActionLoading && pickActionTag === 'complete'" @click="resolvePickComplete(false)" />
              <Button label="Skip - mark done here" variant="outline" theme="gray" class="w-full" :loading="pickActionLoading && pickActionTag === 'complete'" @click="resolvePickComplete(true)" />
            </div>
          </div>
        </div>

        <div v-if="scannerOpen" class="wms-scanner-overlay">
          <div class="wms-scanner-header">
            <p class="text-sm-semibold text-ink-gray-1">{{ { location: 'Scan location barcode', 'receive-sku': 'Scan item barcode', 'pack-sku': 'Scan item barcode', 'stage-bin': 'Scan bin barcode', builder: 'Scan item or bin barcode' }[scannerTarget] || 'Scan item barcode' }}</p>
            <Button icon="lucide-x" aria-label="Close scanner" variant="ghost" theme="gray" class="text-ink-gray-1" @click="closeScanner" />
          </div>
          <div id="wms-scanner-area" class="wms-scanner-area"></div>
          <p v-if="scannerStarting" class="wms-scanner-hint">Requesting camera access...</p>
          <p v-else class="wms-scanner-hint">Point the camera at a barcode or QR code</p>
        </div>

        <div v-if="myTasksDrawerTask" class="wms-create-overlay">
          <div class="wms-create-sheet">
            <div class="flex items-center justify-between border-b border-outline-gray-2 px-3 py-2.5">
              <p class="text-sm-semibold">{{ myTasksDrawerTask.kind }} {{ myTasksDrawerTask.reference }}</p>
              <Button icon="lucide-x" aria-label="Close" variant="ghost" theme="gray" @click="closeTaskDrawer" />
            </div>
            <div class="space-y-3 overflow-y-auto p-3">
              <div class="rounded-4 border border-outline-gray-2 p-3">
                <div class="flex items-center justify-between"><span class="text-sm text-ink-gray-5">Customer</span><span class="text-sm-semibold">{{ myTasksDrawerTask.customer || 'Not set' }}</span></div>
                <div class="mt-2 flex items-center justify-between"><span class="text-sm text-ink-gray-5">Status</span><span class="text-sm-semibold">{{ myTasksDrawerTask.status }}</span></div>
                <div class="mt-2 flex items-center justify-between">
                  <span class="text-sm text-ink-gray-5">Claim</span>
                  <span class="text-sm-semibold" :class="myTasksClaimedByOther ? 'text-ink-orange-6' : 'text-ink-green-6'">
                    {{ myTasksClaimedByOther ? `In progress by ${myTasksDrawerTask.assigned_to.name}` : myTasksClaimedByMe ? 'You have this' : 'Open to claim' }}
                  </span>
                </div>
                <div v-if="myTasksDrawerCreated" class="mt-2 flex items-center justify-between"><span class="text-sm text-ink-gray-5">Created</span><span class="text-sm-semibold">{{ formatDateTime(myTasksDrawerCreated) }}</span></div>
                <div v-if="myTasksDrawerTask.kind === 'Pick' && myTasksDrawerTask.assigned_to?.id" class="mt-2 flex items-center justify-between"><span class="text-sm text-ink-gray-5">Picker</span><span class="text-sm-semibold">{{ myTasksDrawerTask.assigned_to.name }}</span></div>
                <div v-if="myTasksDrawerClaimedAt && !myTasksDrawerIsDone" class="mt-2 flex items-center justify-between"><span class="text-sm text-ink-gray-5">Elapsed</span><span class="text-sm-semibold tabular-nums text-ink-green-7">{{ formatElapsed(myTasksDrawerClaimedAt) }}</span></div>
              </div>
              <div>
                <p class="mb-2 text-sm-semibold">Contents</p>
                <LoadingText v-if="myTasksDrawerItemsLoading" :lines="3" />
                <template v-else>
                  <button v-if="myTasksDrawerSource" type="button" class="mb-2 block w-full rounded-4 border border-outline-gray-2 p-2 text-left" @click="openDesk(myTasksDrawerSource.route)">
                    <div class="flex items-center justify-between gap-2"><p class="text-xs-semibold text-ink-green-6 underline">{{ myTasksDrawerSource.doctype }} {{ myTasksDrawerSource.name }}</p><Badge v-if="myTasksDrawerIntegrity" :label="myTasksDrawerIntegrity.label" :theme="myTasksDrawerIntegrity.status === 'match' ? 'green' : 'orange'" variant="subtle" /></div>
                    <p class="mt-0.5 text-2xs text-ink-gray-5">{{ myTasksDrawerSource.party_name }}<template v-if="myTasksDrawerSource.external_reference"> · {{ myTasksDrawerSource.reference_label || 'PO' }} {{ myTasksDrawerSource.external_reference }}</template><template v-if="myTasksDrawerSource.transaction_date"> · Ordered {{ myTasksDrawerSource.transaction_date }}</template></p>
                  </button>
                  <p v-else class="mb-2 text-2xs text-ink-gray-5">Manually created - no source order linked.</p>
                  <div class="rounded-4 border border-outline-gray-2">
                    <div v-for="item in myTasksDrawerItems" :key="item.sku" class="flex items-center gap-2 border-b border-outline-gray-1 p-2 last:border-0">
                      <div class="wms-item-thumb shrink-0"><img v-if="item.image" :src="item.image" :alt="item.name" /><span v-else class="lucide-shirt size-5 text-ink-green-6" aria-hidden="true" /></div>
                      <div class="min-w-0 flex-1">
                        <div class="flex items-center gap-1.5"><p class="truncate text-sm-semibold">{{ item.name }}</p><Badge v-if="item.exception_reason" :label="item.exception_reason" theme="red" variant="subtle" /></div>
                        <p class="truncate text-2xs text-ink-gray-5">{{ item.sku }}<template v-if="item.source_bin"> · Bin {{ shortBin(item.source_bin) }}</template></p>
                      </div>
                      <p class="shrink-0 text-sm-semibold">×{{ formatQty(item.quantity) }}</p>
                    </div>
                    <p v-if="!myTasksDrawerItems.length" class="p-3 text-center text-xs text-ink-gray-5">No item lines on this task.</p>
                  </div>
                </template>
              </div>
              <div v-if="myTasksDrawerTask.kind === 'Pick' && myTasksDrawerActivity.length">
                <p class="mb-2 text-sm-semibold">Activity</p>
                <div class="divide-y divide-outline-gray-1 rounded-4 border border-outline-gray-2">
                  <button v-for="entry in myTasksDrawerActivity" :key="entry.timestamp + entry.item_code + entry.action_type" type="button" class="block w-full p-3 text-left" @click="openDesk(entry.route)">
                    <div class="flex items-center justify-between gap-2">
                      <p class="truncate text-xs-semibold">{{ entry.action_type }}<template v-if="entry.item_name"> · {{ entry.item_name }}</template></p>
                      <Badge v-if="entry.quantity" :label="`×${formatQty(entry.quantity)}`" theme="green" variant="subtle" />
                    </div>
                    <p class="mt-0.5 text-2xs text-ink-gray-5">{{ PICK_ACTION_DESCRIPTIONS[entry.action_type] || entry.action_type }}</p>
                    <p v-if="entry.exception_reason" class="mt-1 text-2xs text-ink-red-6">{{ entry.exception_reason }}<template v-if="entry.note"> - {{ entry.note }}</template></p>
                    <p class="mt-1 text-2xs text-ink-gray-4">{{ entry.user }} · {{ formatDateTime(entry.timestamp) }}</p>
                    <img v-if="entry.image" :src="entry.image" alt="Exception photo" class="mt-1 h-16 rounded-4 border border-outline-gray-2 object-cover" />
                  </button>
                </div>
              </div>
            </div>
            <div class="space-y-2 border-t border-outline-gray-2 p-3">
              <Button v-if="myTasksDrawerIsDone && myTasksDrawerTask.kind === 'Ship'" label="View full history" variant="outline" theme="green" class="w-full" @click="viewShipHistory(myTasksDrawerTask)" />
              <template v-else-if="!myTasksDrawerIsDone">
                <Button v-if="myTasksClaimedByOther" label="In progress by someone else" variant="outline" theme="gray" class="w-full" disabled />
                <Button v-else :label="myTasksClaimedByMe ? 'Continue' : 'Start'" variant="solid" theme="green" class="w-full" :loading="myTasksClaimLoading || pickActionLoading" @click="startDrawerTask" />
                <Button v-if="myTasksClaimedByMe" label="Release back to queue" variant="ghost" theme="red" class="w-full" :loading="myTasksClaimLoading || pickActionLoading" @click="releaseDrawerTask" />
                <Button v-if="!myTasksClaimedByOther" label="Cancel task" variant="ghost" theme="red" class="w-full" :loading="myTasksClaimLoading || pickActionLoading" @click="cancelDrawerTask" />
              </template>
            </div>
          </div>
        </div>

        <div v-if="builderOpen" class="wms-create-overlay wms-fixed">
          <div class="wms-create-sheet">
            <div class="flex items-center justify-between border-b border-outline-gray-2 px-3 py-2.5">
              <p class="text-sm-semibold">New Pick Task <span class="text-2xs font-normal text-ink-gray-5">(no source order needed)</span></p>
              <Button icon="lucide-x" aria-label="Cancel" variant="ghost" theme="gray" @click="closePickBuilder" />
            </div>
            <div class="space-y-3 overflow-y-auto p-3">
              <p v-if="!builderLines.length" class="py-6 text-center text-xs text-ink-gray-5">Nothing added yet. Scan an item below to start.</p>
              <div v-if="builderLines.length" class="rounded-4 border border-outline-gray-2 bg-surface-base">
                <div class="flex items-center justify-between gap-2 px-3 py-2"><span class="truncate text-xs-semibold text-ink-green-7">{{ builderTaskName }}</span><span class="shrink-0 text-2xs text-ink-gray-5">{{ builderGroups.length }} bin{{ builderGroups.length > 1 ? 's' : '' }}</span></div>
              <div v-for="group in builderGroups" :key="group.warehouse">
                <div class="flex items-center gap-1.5 border-t border-outline-gray-1 bg-surface-gray-1 px-3 py-1.5 text-2xs-semibold text-ink-gray-6"><span class="lucide-map-pin size-3 shrink-0" aria-hidden="true" /><span class="truncate">{{ group.label }}</span></div>
                <div v-for="line in group.lines" :key="line.item_code" class="flex items-center gap-2 border-t border-outline-gray-1 p-2" :class="builderFlashKey === line.item_code ? 'bg-surface-green-1' : ''">
                  <button type="button" class="flex min-w-0 flex-1 items-center gap-2 text-left" @click="builderEditKey = line.item_code">
                    <div class="wms-item-thumb shrink-0"><img v-if="line.image" :src="line.image" :alt="line.item_name" /><span v-else class="lucide-shirt size-5 text-ink-green-6" aria-hidden="true" /></div>
                    <div class="min-w-0"><p class="truncate text-sm-semibold">{{ line.item_name }}</p><p class="truncate text-2xs" :class="builderOver(line) ? 'text-ink-red-5' : 'text-ink-gray-5'">{{ line.item_code }}<template v-if="builderOver(line)"> - only {{ formatQty(builderAvailable(line)) }} available</template></p></div>
                  </button>
                  <div class="flex shrink-0 items-center gap-1">
                    <Button icon="lucide-minus" aria-label="Decrease by 1" size="sm" variant="outline" theme="gray" :disabled="Number(line.quantity) <= 1" @click="setBuilderQty(line, Number(line.quantity) - 1)" />
                    <span class="w-8 text-center text-sm-semibold" :class="builderOver(line) ? 'text-ink-red-5' : ''">{{ line.quantity }}</span>
                    <Button icon="lucide-plus" aria-label="Increase by 1" size="sm" variant="outline" theme="gray" :disabled="Number(line.quantity) >= builderAvailable(line)" @click="setBuilderQty(line, Number(line.quantity) + 1)" />
                  </div>
                </div>
              </div>
              </div>
              <div class="rounded-4 border border-outline-green-3 bg-surface-green-1 p-3">
                <p class="text-sm-semibold text-ink-green-7">Scan or Enter SKU</p>
                <div class="mt-3 flex items-end gap-2">
                  <TextInput ref="builderInput" v-model="builderScan" label="Scan item or bin barcode" class="flex-1" :disabled="builderBusy" @keyup.enter="builderScanSubmit()" />
                  <Button icon="lucide-scan-line" aria-label="Scan barcode with camera" variant="outline" theme="green" @click="openScanner('builder')" />
                </div>
                <p class="mt-2 text-2xs text-ink-gray-5">Each scan adds 1. Scan a bin code to list what is in it.</p>
              </div>

              <div v-if="builderBin" class="rounded-4 border border-outline-gray-2 bg-surface-base">
                <div class="flex items-center justify-between gap-2 border-b border-outline-gray-1 px-3 py-2">
                  <p class="truncate text-xs-semibold text-ink-green-7"><span class="lucide-map-pin mr-1 inline-block size-3.5 align-text-bottom" aria-hidden="true" />{{ builderBin.label }} - tap to add</p>
                  <div class="flex shrink-0 items-center gap-1">
                    <Button v-if="builderBin.items.some((item) => item.available > 0)" label="Add all" size="sm" variant="outline" theme="green" :disabled="builderBusy" @click="addAllFromBuilderBin" />
                    <Button icon="lucide-x" aria-label="Clear bin" size="sm" variant="ghost" theme="gray" @click="builderBin = null" />
                  </div>
                </div>
                <button v-for="item in builderBin.items" :key="item.item_code" type="button" class="flex w-full items-center gap-2 border-b border-outline-gray-1 p-2 text-left last:border-0" :disabled="builderBinLeft(item) < 1" @click="builderScanSubmit(item.item_code)">
                  <div class="wms-item-thumb shrink-0"><img v-if="item.image" :src="item.image" :alt="item.item_name" /><span v-else class="lucide-shirt size-5 text-ink-green-6" aria-hidden="true" /></div>
                  <div class="min-w-0 flex-1"><p class="truncate text-sm-semibold">{{ item.item_name }}</p><p class="truncate text-2xs text-ink-gray-5">{{ item.item_code }} - {{ builderBinCount(item) }}</p></div>
                  <span v-if="builderBinLeft(item) >= 1" class="lucide-plus size-4 shrink-0 text-ink-green-6" aria-hidden="true" />
                </button>
                <p v-if="!builderBin.items.length" class="py-4 text-center text-xs text-ink-gray-5">This bin has no items.</p>
              </div>
            </div>
            <div class="border-t border-outline-gray-2 p-3">
              <Button :label="builderLines.length ? `Create pick task - ${builderLines.length} item${builderLines.length > 1 ? 's' : ''} - ${formatQty(builderUnits)} units` : 'Create pick task'" variant="solid" theme="green" class="w-full" :loading="pickActionLoading && pickActionTag === 'create'" :disabled="!builderCanCreate || pickMutationLoading" @click="submitPickBuilder" />
            </div>
          </div>
        </div>

        <div v-if="builderEditLine" class="wms-create-overlay wms-fixed" style="z-index: 40">
          <div class="wms-create-sheet">
            <div class="flex items-center justify-between border-b border-outline-gray-2 px-3 py-2.5">
              <p class="truncate text-sm-semibold">{{ builderEditLine.item_name }}</p>
              <Button icon="lucide-x" aria-label="Done" variant="ghost" theme="gray" @click="builderEditKey = ''" />
            </div>
            <div class="space-y-3 overflow-y-auto p-3">
              <div>
                <p class="mb-2 text-center text-2xs text-ink-gray-5">Quantity to pick</p>
                <div class="flex items-center justify-center gap-3">
                  <Button icon="lucide-minus" aria-label="Decrease by 1" size="lg" variant="outline" theme="gray" @click="setBuilderQty(builderEditLine, Number(builderEditLine.quantity) - 1)" />
                  <TextInput :model-value="String(builderEditLine.quantity)" type="number" class="w-24 text-center" @update:model-value="setBuilderQty(builderEditLine, $event)" />
                  <Button icon="lucide-plus" aria-label="Increase by 1" size="lg" variant="outline" theme="gray" :disabled="Number(builderEditLine.quantity) >= builderAvailable(builderEditLine)" @click="setBuilderQty(builderEditLine, Number(builderEditLine.quantity) + 1)" />
                </div>
              </div>
              <div>
                <p class="mb-2 text-2xs text-ink-gray-5">Pick from</p>
                <button v-for="loc in builderEditLine.locations" :key="loc.warehouse" type="button" class="mb-2 flex w-full items-center justify-between rounded-4 border p-3 text-left disabled:opacity-50" :class="builderEditLine.warehouse === loc.warehouse ? 'border-outline-green-3 bg-surface-green-1' : 'border-outline-gray-2'" :disabled="loc.available < 1" @click="changeBuilderBin(builderEditLine, loc)">
                  <span class="text-sm-semibold">{{ loc.label }}</span>
                  <Badge :label="`${formatQty(loc.available)} available`" :theme="loc.available > 0 ? 'green' : 'red'" variant="subtle" />
                </button>
              </div>
            </div>
            <div class="space-y-2 border-t border-outline-gray-2 p-3">
              <Button label="Done" variant="solid" theme="green" class="w-full" @click="builderEditKey = ''" />
              <Button label="Remove from pick" variant="ghost" theme="red" class="w-full" @click="removeBuilderLine(builderEditLine)" />
            </div>
          </div>
        </div>

        <div v-if="createFormOpen" class="wms-create-overlay">
          <div class="wms-create-sheet">
            <div class="flex items-center justify-between border-b border-outline-gray-2 px-3 py-2.5">
              <p class="text-sm-semibold">
                New {{ { receive: 'Inbound ASN', pick: 'Pick Task', pack: 'Pack Task', ship: 'Shipment Task' }[createFormType] }}
                <span class="text-2xs font-normal text-ink-gray-5">(no source order needed)</span>
              </p>
              <Button icon="lucide-x" aria-label="Cancel" variant="ghost" theme="gray" @click="closeCreateForm" />
            </div>
            <div class="space-y-3 overflow-y-auto p-3">
              <TextInput v-model="createCustomer" label="Customer (blank = pick any existing)" />
              <TextInput v-if="createFormType === 'receive' || createFormType === 'pick'" v-model="createWarehouse" label="Warehouse (blank = default)" />
              <div v-if="createFormType === 'pack'" class="grid grid-cols-2 gap-1.5">
                <Button v-for="opt in ['Carton Box', 'Poly Mailer', 'Pallet', 'Other']" :key="opt" :label="opt" size="sm" :variant="createPackageType === opt ? 'solid' : 'outline'" theme="green" @click="createPackageType = opt" />
              </div>
              <div v-if="createFormType === 'ship'" class="grid grid-cols-4 gap-1.5">
                <Button v-for="opt in ['UPS', 'FedEx', 'DHL', 'USPS']" :key="opt" :label="opt" size="sm" :variant="createCarrier === opt ? 'solid' : 'outline'" theme="green" @click="createCarrier = opt" />
              </div>
              <div>
                <p class="mb-2 text-sm-semibold">Items</p>
                <div v-for="(row, index) in createItems" :key="index" class="mb-2 flex items-end gap-2">
                  <TextInput v-model="row.item_code" label="Item code" class="flex-1" />
                  <TextInput v-model="row.quantity" type="number" label="Qty" class="w-16" />
                  <Button icon="lucide-x" aria-label="Remove line" variant="outline" theme="gray" :disabled="createItems.length <= 1" @click="removeCreateItemRow(index)" />
                </div>
                <Button label="Add item line" icon-left="lucide-plus" variant="outline" theme="gray" size="sm" class="w-full" @click="addCreateItemRow" />
              </div>
            </div>
            <div class="border-t border-outline-gray-2 p-3">
              <Button label="Create in ERPNext" variant="solid" theme="green" class="w-full" :loading="pickActionLoading && pickActionTag === 'create'" :disabled="pickMutationLoading" @click="submitCreateForm" />
            </div>
          </div>
        </div>

        <nav class="wms-nav fixed bottom-0 left-1/2 z-10 grid w-full max-w-[400px] -translate-x-1/2 grid-cols-4 items-center justify-items-center border-t border-outline-gray-2 bg-surface-base px-4 shadow-lg sm:absolute">
          <Button variant="ghost" theme="gray" icon="lucide-house" aria-label="Home" :class="screen === 'home' ? 'text-ink-green-6' : 'text-ink-gray-7'" @click="goHome" />
          <div class="relative"><Button variant="ghost" theme="gray" icon="lucide-clipboard-list" aria-label="My tasks" :class="showMyTasksList ? 'text-ink-green-6' : 'text-ink-gray-7'" @click="myTasksTab = 'active'; setScreen('tasks')" /><Badge v-if="openTaskCount" :label="String(openTaskCount)" theme="green" variant="solid" class="pointer-events-none absolute -right-1 -top-1" /></div>
          <div class="relative"><Button variant="ghost" theme="gray" icon="lucide-warehouse" aria-label="Inventory" :class="screen === 'inventory' ? 'text-ink-green-6' : 'text-ink-gray-7'" @click="setScreen('inventory')" /><Badge v-if="hasNegativeStock" label="!" theme="red" variant="solid" class="pointer-events-none absolute -right-1 -top-1" /></div>
          <Button variant="ghost" theme="gray" icon="lucide-settings" aria-label="Settings" :class="screen === 'settings' ? 'text-ink-green-6' : 'text-ink-gray-7'" @click="setScreen('settings')" />
        </nav>
      </main>
    </div>
  </FrappeUIProvider>
</template>
