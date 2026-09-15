"""Pestaña de presupuesto y pagos para la vista de orden."""

from __future__ import annotations

import logging
from datetime import datetime

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QComboBox,
    QLineEdit,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QMessageBox,
    QDateEdit,
    QSizePolicy,
    QScrollArea,
)

from luciotech.database.models import ServiceOrder, Payment, BudgetConcept
from luciotech.database.repositories import BudgetConceptRepo
from luciotech.services.order_service import OrderService
from luciotech.config import PAYMENT_TYPES, PAYMENT_METHODS, CONCEPT_TYPES
from luciotech.utils import format_money, currency_prefix
import re

logger = logging.getLogger(__name__)


def _parse_money(text: str) -> float:
    """Extraer el valor numérico de una cadena formateada como dinero."""
    cleaned = re.sub(r'[^\d.\-]', '', text)
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


class BudgetPaymentsTab(QWidget):
    """Pestaña de presupuesto y pagos."""

    def __init__(self, order: ServiceOrder, parent: QWidget | None = None, order_service: OrderService | None = None) -> None:
        super().__init__(parent)
        self._order = order
        # Reusar el OrderService del diálogo padre si se proporciona, para que
        # el objeto order y las operaciones de persistencia compartan la misma
        # sesión SQLAlchemy y evitar "Instance is not persistent within this Session".
        self._order_service = order_service if order_service is not None else OrderService()
        self._init_ui()
        self._load_data()

    def set_order(self, order: ServiceOrder) -> None:
        """Actualizar la orden referenciada y recargar conceptos/pagos en el sitio."""
        self._order = order
        self._load_data()

    def _init_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        # Scroll area para que todo el contenido sea accesible
        # aunque la ventana sea pequeña
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)

        inner_widget = QWidget()
        layout = QVBoxLayout(inner_widget)
        layout.setContentsMargins(8, 8, 8, 8)
        scroll.setWidget(inner_widget)
        outer.addWidget(scroll)

        prefix = currency_prefix()

        # Sección: Conceptos de presupuesto
        budget_group = QGroupBox("Presupuesto")
        budget_layout = QVBoxLayout(budget_group)

        # Tabla de conceptos
        self._concepts_table = QTableWidget()
        self._concepts_table.setColumnCount(5)
        self._concepts_table.setHorizontalHeaderLabels(["Tipo", "Descripción", "Cantidad", "Precio unit.", "Subtotal"])
        self._concepts_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._concepts_table.setAlternatingRowColors(True)
        self._concepts_table.setMinimumHeight(180)
        self._concepts_table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        header = self._concepts_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        budget_layout.addWidget(self._concepts_table)

        # Botones de conceptos
        concept_btn_layout = QHBoxLayout()
        self._btn_add_concept = QPushButton("➕ Añadir concepto")
        self._btn_add_concept.clicked.connect(self._add_concept_row)
        concept_btn_layout.addWidget(self._btn_add_concept)
        self._btn_remove_concept = QPushButton("🗑 Eliminar")
        self._btn_remove_concept.clicked.connect(self._remove_concept_row)
        concept_btn_layout.addWidget(self._btn_remove_concept)
        budget_layout.addLayout(concept_btn_layout)

        layout.addWidget(budget_group)

        # Sección: Estado del presupuesto
        status_group = QGroupBox("Estado del presupuesto")
        status_layout = QHBoxLayout(status_group)

        self._lbl_budget_status_label = QLabel("Estado actual:")
        status_layout.addWidget(self._lbl_budget_status_label)

        self._lbl_budget_status = QLabel("Pendiente")
        self._lbl_budget_status.setStyleSheet("font-size: 14px; font-weight: bold; padding: 4px 8px; border-radius: 4px;")
        status_layout.addWidget(self._lbl_budget_status)

        status_layout.addStretch()

        self._btn_approve_budget = QPushButton("✅ Aprobar presupuesto")
        self._btn_approve_budget.setStyleSheet("background-color: #2ecc71; color: white; font-weight: bold; padding: 6px 12px;")
        self._btn_approve_budget.clicked.connect(self._approve_budget)
        status_layout.addWidget(self._btn_approve_budget)

        self._btn_reject_budget = QPushButton("❌ Rechazar presupuesto")
        self._btn_reject_budget.setStyleSheet("background-color: #e74c3c; color: white; font-weight: bold; padding: 6px 12px;")
        self._btn_reject_budget.clicked.connect(self._reject_budget)
        status_layout.addWidget(self._btn_reject_budget)

        layout.addWidget(status_group)

        # Resumen de costos
        summary_group = QGroupBox("Resumen de costos")
        summary_layout = QFormLayout(summary_group)

        self._lbl_subtotal = QLabel(format_money(0))
        summary_layout.addRow("Subtotal:", self._lbl_subtotal)

        self._spn_parts = QDoubleSpinBox()
        self._spn_parts.setRange(0, 999999)
        self._spn_parts.setPrefix(prefix)
        self._spn_parts.setDecimals(2)
        self._spn_parts.valueChanged.connect(self._recalculate)
        summary_layout.addRow("Valor de repuestos:", self._spn_parts)

        self._spn_labor = QDoubleSpinBox()
        self._spn_labor.setRange(0, 999999)
        self._spn_labor.setPrefix(prefix)
        self._spn_labor.setDecimals(2)
        self._spn_labor.valueChanged.connect(self._recalculate)
        summary_layout.addRow("Valor de reparación:", self._spn_labor)

        summary_layout.addRow(HRLine())

        self._lbl_total = QLabel(format_money(0))
        self._lbl_total.setStyleSheet("font-size: 16px; font-weight: bold;")
        summary_layout.addRow("TOTAL:", self._lbl_total)

        self._lbl_advance = QLabel(format_money(0))
        summary_layout.addRow("Anticipo:", self._lbl_advance)

        self._lbl_paid = QLabel(format_money(0))
        summary_layout.addRow("Pagado:", self._lbl_paid)

        self._lbl_balance = QLabel(format_money(0))
        self._lbl_balance.setStyleSheet("font-size: 16px; font-weight: bold; color: red;")
        summary_layout.addRow("SALDO PENDIENTE:", self._lbl_balance)

        self._btn_recalc = QPushButton("Recalcular")
        self._btn_recalc.clicked.connect(self._recalculate)
        summary_layout.addRow("", self._btn_recalc)

        layout.addWidget(summary_group)

        # Sección: Pagos
        payments_group = QGroupBox("Pagos registrados")
        payments_layout = QVBoxLayout(payments_group)

        self._payments_table = QTableWidget()
        self._payments_table.setColumnCount(6)
        self._payments_table.setHorizontalHeaderLabels(["Fecha", "Tipo", "Método", "Monto", "Referencia", "Estado"])
        self._payments_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._payments_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._payments_table.setAlternatingRowColors(True)
        self._payments_table.setMinimumHeight(150)
        self._payments_table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        ph = self._payments_table.horizontalHeader()
        ph.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        ph.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        ph.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        ph.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        ph.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        ph.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        payments_layout.addWidget(self._payments_table)

        # Botones de pagos
        pay_btn_layout = QHBoxLayout()
        self._btn_add_payment = QPushButton("💵 Registrar pago")
        self._btn_add_payment.clicked.connect(self._register_payment)
        pay_btn_layout.addWidget(self._btn_add_payment)

        self._btn_edit_payment = QPushButton("✏️ Editar pago")
        self._btn_edit_payment.clicked.connect(self._edit_payment)
        pay_btn_layout.addWidget(self._btn_edit_payment)

        self._btn_void_payment = QPushButton("🚫 Anular pago")
        self._btn_void_payment.setStyleSheet("color: #c0392b;")
        self._btn_void_payment.clicked.connect(self._void_payment)
        pay_btn_layout.addWidget(self._btn_void_payment)

        pay_btn_layout.addStretch()
        payments_layout.addLayout(pay_btn_layout)

        layout.addWidget(payments_group)

        # Botones finales
        final_layout = QHBoxLayout()
        self._btn_save_budget = QPushButton("💾 Guardar presupuesto")
        self._btn_save_budget.clicked.connect(self._save_budget)
        final_layout.addWidget(self._btn_save_budget)
        final_layout.addStretch()
        layout.addLayout(final_layout)

    def _load_data(self) -> None:
        """Cargar conceptos y pagos."""
        from luciotech.database.repositories import PaymentRepo

        # Reusar la sesión del order_service para evitar DetachedInstanceError
        session = self._order_service.session
        pay_repo = PaymentRepo(session)
        payments = pay_repo.get_by_order(self._order.id)

        # Load persisted budget concepts
        concept_repo = BudgetConceptRepo(session)
        concepts = concept_repo.get_by_order(self._order.id)

        self._concepts_table.setRowCount(0)
        for concept in concepts:
            self._add_concept_row(
                concept_type=concept.concept_type,
                description=concept.description,
                quantity=concept.quantity,
                unit_price=concept.unit_price,
            )

        self._spn_parts.setValue(self._order.parts_cost or 0.0)
        self._spn_labor.setValue(self._order.labor_cost or 0.0)

        # Load payments
        self._payments_table.setRowCount(0)
        total_paid = 0.0
        for row, p in enumerate(payments):
            self._payments_table.insertRow(row)

            # Guardar el objeto Payment en UserRole para recuperarlo en editar/anular
            date_item = QTableWidgetItem(p.payment_date.strftime("%Y-%m-%d") if p.payment_date else "")
            date_item.setData(Qt.ItemDataRole.UserRole, p)
            self._payments_table.setItem(row, 0, date_item)

            self._payments_table.setItem(row, 1, QTableWidgetItem(p.payment_type))
            self._payments_table.setItem(row, 2, QTableWidgetItem(p.payment_method))
            self._payments_table.setItem(row, 3, QTableWidgetItem(format_money(p.amount)))
            self._payments_table.setItem(row, 4, QTableWidgetItem(p.reference or ""))

            estado_item = QTableWidgetItem("Anulado" if p.is_voided else "Activo")
            if p.is_voided:
                estado_item.setForeground(Qt.GlobalColor.red)
                # Tachar visualmente toda la fila
                for col in range(5):
                    it = self._payments_table.item(row, col)
                    if it:
                        font = it.font()
                        font.setStrikeOut(True)
                        it.setFont(font)
                        it.setForeground(Qt.GlobalColor.gray)
            self._payments_table.setItem(row, 5, estado_item)

            if not p.is_voided:
                total_paid += p.amount

        # Update summary
        self._recalculate()
        self._lbl_advance.setText(format_money(self._order.advance_payment))
        self._lbl_paid.setText(format_money(total_paid))
        self._lbl_balance.setText(format_money(self._order.balance))

        # Update budget status indicator
        self._update_budget_status_display()

    def _update_budget_status_display(self) -> None:
        """Actualizar la etiqueta de estado del presupuesto con colores."""
        status = getattr(self._order, "budget_status", None) or "Pendiente"
        self._lbl_budget_status.setText(status)

        color_map = {
            "Pendiente": ("background-color: #f39c12; color: white;", True, True),
            "Aprobado": ("background-color: #2ecc71; color: white;", False, False),
            "Rechazado": ("background-color: #e74c3c; color: white;", False, False),
        }
        style, can_approve, can_reject = color_map.get(status, ("background-color: #95a5a6; color: white;", True, True))
        self._lbl_budget_status.setStyleSheet(
            f"font-size: 14px; font-weight: bold; padding: 4px 8px; border-radius: 4px; {style}"
        )
        self._btn_approve_budget.setEnabled(can_approve)
        self._btn_reject_budget.setEnabled(can_reject)

    def _set_budget_status(self, new_status: str) -> None:
        """Cambiar el estado del presupuesto.

        Al aprobar:
        1. Persiste los conceptos que están en la tabla UI (igual que Guardar).
        2. Calcula parts_cost, labor_cost, total y balance.
        3. Guarda todo en la orden.
        4. Cambia budget_status y registra el evento en el historial.
        """
        from luciotech.database.repositories import PaymentRepo

        session = self._order_service.session
        old_status = getattr(self._order, "budget_status", None) or "Pendiente"

        if new_status == "Aprobado":
            # ── Paso 1: leer filas de la tabla UI y persistirlas ──────────────
            concept_repo = BudgetConceptRepo(session)
            concepts = []
            for row in range(self._concepts_table.rowCount()):
                type_combo = self._concepts_table.cellWidget(row, 0)
                desc_item  = self._concepts_table.item(row, 1)
                qty_spin   = self._concepts_table.cellWidget(row, 2)
                price_spin = self._concepts_table.cellWidget(row, 3)
                if not (type_combo and qty_spin and price_spin):
                    continue
                qty        = qty_spin.value()
                unit_price = price_spin.value()
                subtotal   = qty * unit_price
                concepts.append(BudgetConcept(
                    order_id     = self._order.id,
                    concept_type = type_combo.currentText(),
                    description  = desc_item.text().strip() if desc_item else "",
                    quantity     = qty,
                    unit_price   = unit_price,
                    subtotal     = subtotal,
                ))
            concept_repo.replace_for_order(self._order.id, concepts)

            # ── Paso 2: calcular totales ──────────────────────────────────────
            # Si hay conceptos detallados, desglosar por tipo; si no, usar spinners.
            if concepts:
                parts_cost = sum(
                    c.subtotal for c in concepts
                    if c.concept_type in ("Repuesto", "Accesorio")
                )
                labor_cost = sum(
                    c.subtotal for c in concepts
                    if c.concept_type in ("Mano de obra", "Diagnóstico", "Servicio", "Otro")
                )
            else:
                parts_cost = self._spn_parts.value()
                labor_cost = self._spn_labor.value()

            total      = parts_cost + labor_cost
            total_paid = PaymentRepo(session).get_total_paid(self._order.id)
            balance    = total - total_paid

            # ── Paso 3: persistir en la orden ─────────────────────────────────
            self._order.parts_cost    = parts_cost
            self._order.labor_cost    = labor_cost
            self._order.discount      = 0.0
            self._order.tax           = 0.0
            self._order.total         = total
            self._order.advance_payment = self._order.advance_payment or 0.0
            self._order.balance       = balance

            # ── Paso 4: actualizar UI inmediatamente ──────────────────────────
            self._spn_parts.blockSignals(True)
            self._spn_labor.blockSignals(True)
            self._spn_parts.setValue(parts_cost)
            self._spn_labor.setValue(labor_cost)
            self._spn_parts.blockSignals(False)
            self._spn_labor.blockSignals(False)
            self._lbl_subtotal.setText(format_money(sum(c.subtotal for c in concepts)))
            self._lbl_total.setText(format_money(total))
            self._lbl_advance.setText(format_money(self._order.advance_payment))
            self._lbl_paid.setText(format_money(total_paid))
            self._lbl_balance.setText(format_money(balance))

            logger.info(
                "Presupuesto aprobado para orden %s: repuestos=%.2f, "
                "reparación=%.2f, total=%.2f, pagado=%.2f, saldo=%.2f",
                self._order.order_number, parts_cost, labor_cost,
                total, total_paid, balance,
            )

        # ── Paso 5: cambiar estado y persistir ───────────────────────────────
        self._order.budget_status = new_status
        self._order_service.order_repo.update(self._order)

        event_type  = "Presupuesto aprobado" if new_status == "Aprobado" else "Presupuesto rechazado"
        title       = f"Presupuesto {new_status.lower()}"
        extra       = (
            f" Total: {format_money(self._order.total)}, "
            f"Saldo: {format_money(self._order.balance)}."
            if new_status == "Aprobado" else ""
        )
        description = f"Estado del presupuesto cambiado de '{old_status}' a '{new_status}'.{extra}"
        self._order_service.add_event(self._order, event_type, title, description)

        self._update_budget_status_display()
        logger.info(
            "Presupuesto de orden %s: %s → %s",
            self._order.order_number, old_status, new_status,
        )

    def _approve_budget(self) -> None:
        """Aprobar el presupuesto de la orden."""
        reply = QMessageBox.question(
            self,
            "Aprobar presupuesto",
            "¿Está seguro de que desea aprobar el presupuesto de esta orden?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._set_budget_status("Aprobado")
            QMessageBox.information(self, "Presupuesto aprobado", "El presupuesto ha sido aprobado.")

    def _reject_budget(self) -> None:
        """Rechazar el presupuesto de la orden."""
        reply = QMessageBox.question(
            self,
            "Rechazar presupuesto",
            "¿Está seguro de que desea rechazar el presupuesto de esta orden?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._set_budget_status("Rechazado")
            QMessageBox.information(self, "Presupuesto rechazado", "El presupuesto ha sido rechazado.")

    def _add_concept_row(
        self,
        concept_type: str = "",
        description: str = "",
        quantity: float = 1.0,
        unit_price: float = 0.0,
    ) -> None:
        row = self._concepts_table.rowCount()
        self._concepts_table.insertRow(row)
        prefix = currency_prefix()

        type_combo = QComboBox()
        type_combo.addItems(CONCEPT_TYPES)
        if concept_type and concept_type in CONCEPT_TYPES:
            type_combo.setCurrentText(concept_type)
        self._concepts_table.setCellWidget(row, 0, type_combo)

        desc_item = QTableWidgetItem(description)
        self._concepts_table.setItem(row, 1, desc_item)

        qty_spin = QDoubleSpinBox()
        qty_spin.setRange(0, 9999)
        qty_spin.setValue(quantity)
        self._concepts_table.setCellWidget(row, 2, qty_spin)

        price_spin = QDoubleSpinBox()
        price_spin.setRange(0, 999999)
        price_spin.setPrefix(prefix)
        price_spin.setValue(unit_price)
        self._concepts_table.setCellWidget(row, 3, price_spin)

        subtotal_label = QLabel(format_money(0))
        self._concepts_table.setCellWidget(row, 4, subtotal_label)

        def calc():
            sub = qty_spin.value() * price_spin.value()
            subtotal_label.setText(format_money(sub))
        qty_spin.valueChanged.connect(calc)
        price_spin.valueChanged.connect(calc)
        calc()

    def _remove_concept_row(self) -> None:
        row = self._concepts_table.currentRow()
        if row >= 0:
            self._concepts_table.removeRow(row)

    def _recalculate(self) -> None:
        """Recalcular totales desde la tabla de conceptos."""
        subtotal = 0
        for row in range(self._concepts_table.rowCount()):
            sub_widget = self._concepts_table.cellWidget(row, 4)
            if sub_widget and isinstance(sub_widget, QLabel):
                subtotal += _parse_money(sub_widget.text())

        total = self._spn_parts.value() + self._spn_labor.value()

        self._lbl_subtotal.setText(format_money(subtotal))
        self._lbl_total.setText(format_money(total))

    def _register_payment(self) -> None:
        """Diálogo para registrar un pago."""
        from PyQt6.QtWidgets import QDialog, QFormLayout, QComboBox, QDoubleSpinBox, QLineEdit, QPushButton, QHBoxLayout, QDateEdit

        dialog = QDialog(self)
        dialog.setWindowTitle("Registrar pago")
        dialog.setMinimumWidth(350)

        layout = QFormLayout(dialog)

        type_combo = QComboBox()
        type_combo.addItems(PAYMENT_TYPES)
        layout.addRow("Tipo de pago:", type_combo)

        method_combo = QComboBox()
        method_combo.addItems(PAYMENT_METHODS)
        layout.addRow("Método de pago:", method_combo)

        amount_spin = QDoubleSpinBox()
        amount_spin.setRange(0.01, 999999)
        amount_spin.setPrefix(currency_prefix())
        amount_spin.setValue(self._order.balance if self._order.balance > 0 else 0)
        layout.addRow("Monto:", amount_spin)

        ref_input = QLineEdit()
        ref_input.setPlaceholderText("Número de referencia, comprobante...")
        layout.addRow("Referencia:", ref_input)

        notes_input = QLineEdit()
        notes_input.setPlaceholderText("Observaciones...")
        layout.addRow("Observaciones:", notes_input)

        btn_layout = QHBoxLayout()
        btn_save = QPushButton("Registrar")
        btn_cancel = QPushButton("Cancelar")

        def do_save():
            try:
                payment = self._order_service.add_payment(
                    self._order,
                    type_combo.currentText(),
                    method_combo.currentText(),
                    amount_spin.value(),
                    ref_input.text(),
                    notes_input.text(),
                )
                QMessageBox.information(dialog, "Pago registrado", f"Pago de {format_money(amount_spin.value())} registrado.")
                self._load_data()
                dialog.accept()
            except Exception as e:
                QMessageBox.warning(dialog, "Error", str(e))

        btn_save.clicked.connect(do_save)
        btn_cancel.clicked.connect(dialog.reject)
        btn_layout.addWidget(btn_save)
        btn_layout.addWidget(btn_cancel)
        layout.addRow(btn_layout)

        dialog.exec()

    def _get_selected_payment(self) -> Payment | None:
        """Devolver el Payment de la fila seleccionada, o None si no hay selección."""
        row = self._payments_table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "Sin selección", "Selecciona un pago de la tabla primero.")
            return None
        item = self._payments_table.item(row, 0)
        if item is None:
            return None
        payment = item.data(Qt.ItemDataRole.UserRole)
        return payment

    def _edit_payment(self) -> None:
        """Diálogo para editar un pago existente."""
        from PyQt6.QtWidgets import QDialog, QFormLayout, QComboBox, QDoubleSpinBox, QLineEdit, QPushButton, QHBoxLayout

        payment = self._get_selected_payment()
        if payment is None:
            return
        if payment.is_voided:
            QMessageBox.warning(self, "Pago anulado", "No se puede editar un pago anulado.")
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("Editar pago")
        dialog.setMinimumWidth(350)
        layout = QFormLayout(dialog)

        type_combo = QComboBox()
        type_combo.addItems(PAYMENT_TYPES)
        type_combo.setCurrentText(payment.payment_type)
        layout.addRow("Tipo de pago:", type_combo)

        method_combo = QComboBox()
        method_combo.addItems(PAYMENT_METHODS)
        method_combo.setCurrentText(payment.payment_method)
        layout.addRow("Método de pago:", method_combo)

        amount_spin = QDoubleSpinBox()
        amount_spin.setRange(0.01, 999999)
        amount_spin.setPrefix(currency_prefix())
        amount_spin.setValue(payment.amount)
        layout.addRow("Monto:", amount_spin)

        ref_input = QLineEdit(payment.reference or "")
        ref_input.setPlaceholderText("Número de referencia, comprobante...")
        layout.addRow("Referencia:", ref_input)

        notes_input = QLineEdit(payment.notes or "")
        notes_input.setPlaceholderText("Observaciones...")
        layout.addRow("Observaciones:", notes_input)

        btn_layout = QHBoxLayout()
        btn_save = QPushButton("Guardar cambios")
        btn_cancel = QPushButton("Cancelar")

        def do_save():
            try:
                self._order_service.edit_payment(
                    payment.id,
                    payment_type=type_combo.currentText(),
                    payment_method=method_combo.currentText(),
                    amount=amount_spin.value(),
                    reference=ref_input.text(),
                    notes=notes_input.text(),
                )
                # Recargar orden para obtener saldo actualizado
                self._order = self._order_service.get_by_id(self._order.id)
                self._load_data()
                dialog.accept()
                QMessageBox.information(self, "Pago editado", "El pago fue actualizado correctamente.")
            except Exception as e:
                QMessageBox.warning(dialog, "Error", str(e))

        btn_save.clicked.connect(do_save)
        btn_cancel.clicked.connect(dialog.reject)
        btn_layout.addWidget(btn_save)
        btn_layout.addWidget(btn_cancel)
        layout.addRow(btn_layout)
        dialog.exec()

    def _void_payment(self) -> None:
        """Confirmar y anular el pago seleccionado."""
        from PyQt6.QtWidgets import QDialog, QFormLayout, QLineEdit, QPushButton, QHBoxLayout, QLabel

        payment = self._get_selected_payment()
        if payment is None:
            return
        if payment.is_voided:
            QMessageBox.warning(self, "Ya anulado", "Este pago ya está anulado.")
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("Anular pago")
        dialog.setMinimumWidth(380)
        layout = QFormLayout(dialog)

        info = QLabel(
            f"<b>Tipo:</b> {payment.payment_type} &nbsp;|&nbsp; "
            f"<b>Monto:</b> {format_money(payment.amount)} &nbsp;|&nbsp; "
            f"<b>Método:</b> {payment.payment_method}"
        )
        info.setWordWrap(True)
        layout.addRow(info)

        reason_input = QLineEdit()
        reason_input.setPlaceholderText("Motivo de la anulación (obligatorio)...")
        layout.addRow("Razón:", reason_input)

        btn_layout = QHBoxLayout()
        btn_void = QPushButton("🚫 Anular")
        btn_void.setStyleSheet("background-color: #c0392b; color: white; font-weight: bold;")
        btn_cancel = QPushButton("Cancelar")

        def do_void():
            reason = reason_input.text().strip()
            if not reason:
                QMessageBox.warning(dialog, "Razón requerida", "Debes ingresar un motivo para anular el pago.")
                return
            try:
                self._order_service.void_payment(payment.id, reason)
                # Recargar orden para obtener saldo actualizado
                self._order = self._order_service.get_by_id(self._order.id)
                self._load_data()
                dialog.accept()
                QMessageBox.information(self, "Pago anulado", "El pago fue anulado y el saldo fue recalculado.")
            except Exception as e:
                QMessageBox.warning(dialog, "Error", str(e))

        btn_void.clicked.connect(do_void)
        btn_cancel.clicked.connect(dialog.reject)
        btn_layout.addWidget(btn_void)
        btn_layout.addWidget(btn_cancel)
        layout.addRow(btn_layout)
        dialog.exec()

    def _save_budget(self) -> None:
        """Guardar presupuesto calculado con conceptos persistentes."""
        from luciotech.database.repositories import PaymentRepo

        # Usar siempre la misma sesión que order_repo para evitar
        # DetachedInstanceError al guardar el objeto order
        session = self._order_service.session
        concept_repo = BudgetConceptRepo(session)

        concepts = []
        subtotal = 0.0
        for row in range(self._concepts_table.rowCount()):
            type_combo = self._concepts_table.cellWidget(row, 0)
            desc_item = self._concepts_table.item(row, 1)
            qty_spin = self._concepts_table.cellWidget(row, 2)
            price_spin = self._concepts_table.cellWidget(row, 3)

            if not (type_combo and qty_spin and price_spin):
                continue

            concept_type = type_combo.currentText()
            description = desc_item.text().strip() if desc_item else ""
            quantity = qty_spin.value()
            unit_price = price_spin.value()
            line_subtotal = quantity * unit_price
            subtotal += line_subtotal

            concepts.append(BudgetConcept(
                order_id=self._order.id,
                concept_type=concept_type,
                description=description,
                quantity=quantity,
                unit_price=unit_price,
                subtotal=line_subtotal,
            ))

        concept_repo.replace_for_order(self._order.id, concepts)

        parts_cost = self._spn_parts.value()
        labor_cost = self._spn_labor.value()
        total = parts_cost + labor_cost

        self._order.parts_cost = parts_cost
        self._order.labor_cost = labor_cost
        self._order.discount = 0.0
        self._order.tax = 0.0
        self._order.total = total
        total_paid = PaymentRepo(session).get_total_paid(self._order.id)
        self._order.balance = total - total_paid
        self._order_service.order_repo.update(self._order)

        self._recalculate()
        self._lbl_paid.setText(format_money(total_paid))
        self._lbl_balance.setText(format_money(self._order.balance))

        QMessageBox.information(self, "Guardado", f"Presupuesto guardado. Total: {format_money(self._order.total)}")
        logger.info("Presupuesto guardado para orden %s: %.2f (%d conceptos)",
                     self._order.order_number, self._order.total, len(concepts))


class HRLine(QWidget):
    """Línea horizontal separadora."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(2)
        from PyQt6.QtGui import QPalette
        self.setStyleSheet(f"background-color: {self.palette().color(QPalette.ColorRole.Mid).name()};")
