import os
import requests
import json
import io
import uuid
from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for, send_file
from flask_login import login_required, current_user
from datetime import datetime, timedelta
import logging
from sqlalchemy.orm import sessionmaker

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

flight_bp = Blueprint('flight', __name__)

# Import xhtml2pdf for PDF generation
try:
    from xhtml2pdf import pisa
    HAS_XHTML2PDF = True
    logger.info("xhtml2pdf available for PDF generation")
except ImportError:
    HAS_XHTML2PDF = False
    logger.warning("xhtml2pdf not installed. PDF generation will use fallback text format.")

class FlightAPI:
    def __init__(self):
        self.base_url = os.getenv("FLIGHT_API_BASE_URL", "https://test.api.amadeus.com").strip()
        self.api_key = os.getenv("FLIGHT_API_KEY", "yzhJybIfaxceYdNmgd95kugTWW4mFAfJ")
        self.sc_key = os.getenv("FLIGHT_SC_KEY", "cYAmmB98bbdrcylC")
        self.access_token = None
        self.token_expiry = None
    
    def get_access_token(self):
        """Get access token from Amadeus API"""
        try:
            url = f"{self.base_url}/v1/security/oauth2/token"
            headers = {
                'Content-Type': 'application/x-www-form-urlencoded'
            }
            data = {
                'grant_type': 'client_credentials',
                'client_id': self.api_key,
                'client_secret': self.sc_key
            }
            
            response = requests.post(url, headers=headers, data=data)
            if response.status_code == 200:
                token_data = response.json()
                self.access_token = token_data['access_token']
                self.token_expiry = datetime.now() + timedelta(seconds=token_data['expires_in'])
                logger.info("Successfully obtained access token")
                return True
            else:
                logger.error(f"Failed to get access token: {response.status_code} - {response.text}")
                return False
        except Exception as e:
            logger.error(f"Error getting access token: {str(e)}")
            return False
    
    def is_token_valid(self):
        """Check if current token is still valid"""
        if not self.access_token or not self.token_expiry:
            return False
        return datetime.now() < self.token_expiry
    
    def search_flights(self, origin, destination, departure_date, return_date=None, adults=1, travel_class='ECONOMY'):
        """Search for flights using Amadeus API"""
        try:
            if not self.is_token_valid():
                if not self.get_access_token():
                    return None, "Failed to authenticate with flight API"
            
            url = f"{self.base_url}/v2/shopping/flight-offers"
            headers = {
                'Authorization': f'Bearer {self.access_token}',
                'Content-Type': 'application/json'
            }
            
            params = {
                'originLocationCode': origin.upper(),
                'destinationLocationCode': destination.upper(),
                'departureDate': departure_date,
                'adults': adults,
                'currencyCode': 'USD',
                'max': 10
            }
            
            if return_date:
                params['returnDate'] = return_date
            
            response = requests.get(url, headers=headers, params=params)
            
            if response.status_code == 200:
                data = response.json()
                return self.parse_flight_data(data), None
            else:
                logger.error(f"Flight search failed: {response.status_code} - {response.text}")
                return None, f"API Error: {response.status_code}"
                
        except Exception as e:
            logger.error(f"Error searching flights: {str(e)}")
            return None, f"Search error: {str(e)}"
    
    def parse_flight_data(self, data):
        """Parse Amadeus API response into simplified format"""
        flights = []
        
        if not data.get('data'):
            return flights
        
        for offer in data['data']:
            try:
                itinerary = offer['itineraries'][0]
                segments = itinerary['segments']
                
                duration = itinerary['duration']
                price = offer['price']['total']
                airline_code = segments[0]['carrierCode']
                airline = self.get_airline_name(airline_code)
                
                departure_time = segments[0]['departure']['at'].split('T')[1][:5]
                arrival_time = segments[-1]['arrival']['at'].split('T')[1][:5]
                stops = len(segments) - 1
                
                flight_data = {
                    'id': offer['id'],
                    'origin': segments[0]['departure']['iataCode'],
                    'destination': segments[-1]['arrival']['iataCode'],
                    'departure_time': departure_time,
                    'arrival_time': arrival_time,
                    'duration': duration.replace('PT', '').replace('H', 'h ').replace('M', 'm'),
                    'airline': airline,
                    'stops': stops,
                    'price': float(price),
                    'travel_class': offer['travelerPricings'][0]['fareDetailsBySegment'][0]['cabin']
                }
                
                flights.append(flight_data)
                
            except Exception as e:
                logger.error(f"Error parsing flight offer: {str(e)}")
                continue
        
        flights.sort(key=lambda x: x['price'])
        return flights
    
    def get_airline_name(self, code):
        """Get airline name from code"""
        airlines = {
            'AA': 'American Airlines',
            'DL': 'Delta Air Lines',
            'UA': 'United Airlines',
            'LH': 'Lufthansa',
            'BA': 'British Airways',
            'AF': 'Air France',
            'EK': 'Emirates',
            'SQ': 'Singapore Airlines',
            'CX': 'Cathay Pacific',
            'QF': 'Qantas'
        }
        return airlines.get(code, code)

# Initialize flight API
flight_api = FlightAPI()

@flight_bp.route('/api/search-flights', methods=['POST'])
def search_flights():
    """API endpoint for flight search"""
    try:
        data = request.get_json()
        
        required_fields = ['origin', 'destination', 'departure_date']
        for field in required_fields:
            if not data.get(field):
                return jsonify({
                    'success': False,
                    'error': f'Missing required field: {field}'
                }), 400
        
        flights, error = flight_api.search_flights(
            origin=data['origin'],
            destination=data['destination'],
            departure_date=data['departure_date'],
            return_date=data.get('return_date'),
            adults=int(data.get('adults', 1)),
            travel_class=data.get('travel_class', 'ECONOMY')
        )
        
        if error:
            return jsonify({
                'success': False,
                'error': error
            }), 500
        
        return jsonify({
            'success': True,
            'flights': flights
        })
        
    except Exception as e:
        logger.error(f"Error in search_flights endpoint: {str(e)}")
        return jsonify({
            'success': False,
            'error': 'Internal server error'
        }), 500

@flight_bp.route('/api/book-flight', methods=['POST'])
@login_required
def book_flight():
    """Book a flight and save to database"""
    try:
        data = request.get_json()
        
        # Validate required fields
        required_fields = ['flight_data', 'passenger_info', 'payment_method']
        for field in required_fields:
            if field not in data:
                return jsonify({
                    'success': False,
                    'error': f'Missing required field: {field}'
                }), 400
        
        # Import your database models and engine
        from main import engine, Flight, Passenger, Booking, Payment
        
        Session = sessionmaker(bind=engine)
        session = Session()
        
        # Create a new flight record from the API data
        flight_data = data['flight_data']
        
        # Check if we already have this flight in database to avoid duplicates
        existing_flight = session.query(Flight).filter_by(
            departure_airport=flight_data['origin'],
            destination_airport=flight_data['destination'],
            airline=flight_data['airline']
        ).first()
        
        if existing_flight:
            flight = existing_flight
        else:
            # Create new flight record
            flight = Flight(
                flight_number=f"API{flight_data['id'][:6]}",
                airline=flight_data['airline'],
                departure_city=flight_data['origin'],
                departure_airport=flight_data['origin'],
                destination_city=flight_data['destination'],
                destination_airport=flight_data['destination'],
                departure_time=datetime.now() + timedelta(days=7),
                arrival_time=datetime.now() + timedelta(days=7, hours=2),
                duration=flight_data['duration'],
                price=flight_data['price'],
                travel_class=flight_data.get('travel_class', 'ECONOMY'),
                stops=flight_data.get('stops', 0),
                available_seats=100
            )
            session.add(flight)
        
        session.flush()  # Get the flight ID
        
        # Create passenger record - LINK TO CURRENT USER
        passenger_info = data['passenger_info']
        
        # First, check if passenger already exists for this user
        existing_passenger = session.query(Passenger).filter_by(
            email=current_user.email,
            user_id=current_user.id
        ).first()
        
        if existing_passenger:
            passenger = existing_passenger
            # Update passenger details
            passenger.first_name = passenger_info['first_name']
            passenger.last_name = passenger_info['last_name']
            passenger.phone = passenger_info['phone']
            passenger.passport_number = passenger_info['passport']
            passenger.special_requests = passenger_info.get('special_requests', '')
        else:
            # Create new passenger record linked to user
            passenger = Passenger(
                user_id=current_user.id,  # ⭐️ CRITICAL: Link passenger to user
                first_name=passenger_info['first_name'],
                last_name=passenger_info['last_name'],
                email=current_user.email,  # Use user's email to ensure consistency
                phone=passenger_info['phone'],
                passport_number=passenger_info['passport'],
                special_requests=passenger_info.get('special_requests', '')
            )
            session.add(passenger)
        
        session.flush()  # Get the passenger ID
        
        # Generate unique booking reference
        booking_ref = f"FLY{datetime.now().strftime('%Y%m%d')}{uuid.uuid4().hex[:8].upper()}"
        ticket_number = f"TKT{datetime.now().strftime('%Y%m%d')}{uuid.uuid4().hex[:6].upper()}"
        
        # Create booking record
        booking = Booking(
        booking_reference=booking_ref,
        flight_id=flight.id,
        passenger_id=passenger.id,
        user_id=current_user.id,  # ✅ add this
        payment_method=data['payment_method'],
        total_amount=flight.price,
        ticket_number=ticket_number,
        status='Confirmed',
        payment_status='Completed',
        payment_date=datetime.utcnow()
)
        session.add(booking)
        session.flush()  # Get the booking ID
        
        # Create payment record
        payment_ref = f"PAY{datetime.now().strftime('%Y%m%d')}{uuid.uuid4().hex[:8].upper()}"
        payment = Payment(
            booking_id=booking.id,
            payment_reference=payment_ref,
            amount=flight.price,
            payment_method=data['payment_method'],
            payment_date=datetime.utcnow(),
            status='Completed',
            card_last_four=None
        )
        session.add(payment)
        
        # Update available seats
        if flight.available_seats > 0:
            flight.available_seats -= 1
        
        session.commit()
        
        session.close()
        
        return jsonify({
            'success': True,
            'booking_reference': booking_ref,
            'ticket_number': ticket_number,
            'invoice_url': f'/flight/api/download-invoice/{booking_ref}',
            'message': 'Flight booked successfully!'
        })
        
    except Exception as e:
        session.rollback()
        logger.error(f"Error booking flight: {str(e)}")
        return jsonify({
            'success': False,
            'error': f'Failed to book flight: {str(e)}'
        }), 500
    
@flight_bp.route('/api/download-invoice/<booking_ref>')
@login_required
def download_invoice(booking_ref):
    """Download booking invoice as PDF"""
    try:
        from main import engine, Booking, Passenger, Flight, Payment
        
        Session = sessionmaker(bind=engine)
        session = Session()
        
        booking = session.query(Booking).filter_by(booking_reference=booking_ref).first()
        if not booking:
            return jsonify({'error': 'Booking not found'}), 404
        
        passenger = session.query(Passenger).filter_by(id=booking.passenger_id).first()
        flight = session.query(Flight).filter_by(id=booking.flight_id).first()
        payment = session.query(Payment).filter_by(booking_id=booking.id).first()
        
        # Generate PDF in memory using xhtml2pdf
        pdf_buffer = generate_invoice_pdf(booking, passenger, flight, payment)
        
        session.close()
        
        if pdf_buffer:
            return send_file(
                pdf_buffer,
                as_attachment=True,
                download_name=f'invoice_{booking_ref}.pdf',
                mimetype='application/pdf'
            )
        else:
            # Fallback to text invoice
            text_invoice = generate_text_invoice(booking, passenger, flight, payment)
            text_buffer = io.BytesIO()
            text_buffer.write(text_invoice.encode('utf-8'))
            text_buffer.seek(0)
            
            return send_file(
                text_buffer,
                as_attachment=True,
                download_name=f'invoice_{booking_ref}.txt',
                mimetype='text/plain'
            )
        
    except Exception as e:
        logger.error(f"Error generating invoice: {str(e)}")
        return jsonify({'error': 'Failed to generate invoice'}), 500

@flight_bp.route('/api/booking-history')
@login_required
def booking_history():
    """Get user's booking history with enhanced statistics"""
    try:
        from main import engine, Booking, Passenger, Flight, Payment
        
        Session = sessionmaker(bind=engine)
        session = Session()
        
        # Get bookings for current user - SIMPLIFIED QUERY
        bookings = session.query(Booking).filter(
            Booking.user_id == current_user.id
        ).order_by(Booking.booking_date.desc()).all()
        
        logger.info(f"Found {len(bookings)} bookings for user {current_user.id}")
        
        history = []
        for booking in bookings:
            flight = session.query(Flight).filter_by(id=booking.flight_id).first()
            passenger = session.query(Passenger).filter_by(id=booking.passenger_id).first()
            
            if flight:
                history.append({
                    'booking_reference': booking.booking_reference,
                    'ticket_number': booking.ticket_number,
                    'flight_number': flight.flight_number,
                    'route': f"{flight.departure_city} → {flight.destination_city}",
                    'departure_date': flight.departure_time.strftime('%Y-%m-%d'),
                    'departure_time': flight.departure_time.strftime('%H:%M'),
                    'status': booking.status,
                    'total_amount': float(booking.total_amount),
                    'booking_date': booking.booking_date.strftime('%Y-%m-%d %H:%M'),
                    'payment_status': booking.payment_status,
                    'refund_requested': booking.refund_requested,
                    'refund_status': booking.refund_status or 'Not Requested',
                    'travel_class': flight.travel_class,
                    'airline': flight.airline,
                    'passenger_name': f"{passenger.first_name} {passenger.last_name}" if passenger else "Unknown"
                })
        
        session.close()
        
        return jsonify({
            'success': True,
            'bookings': history
        })
        
    except Exception as e:
        logger.error(f"Error fetching booking history: {str(e)}")
        return jsonify({
            'success': False,
            'error': f'Failed to fetch booking history: {str(e)}'
        }), 500

@flight_bp.route('/api/request-refund/<booking_ref>', methods=['POST'])
@login_required
def request_refund(booking_ref):
    """Request refund for a booking"""
    try:
        from main import engine, Booking
        
        Session = sessionmaker(bind=engine)
        session = Session()
        
        booking = session.query(Booking).filter_by(booking_reference=booking_ref).first()
        if not booking:
            return jsonify({'error': 'Booking not found'}), 404
        
        # Check if refund can be requested (within 24 hours of booking)
        time_since_booking = datetime.utcnow() - booking.booking_date
        if time_since_booking.total_seconds() > 24 * 3600:  # 24 hours
            return jsonify({
                'success': False,
                'error': 'Refund can only be requested within 24 hours of booking'
            }), 400
        
        booking.refund_requested = True
        booking.refund_status = 'Pending'
        booking.refund_date = datetime.utcnow()
        
        session.commit()
        session.close()
        
        return jsonify({
            'success': True,
            'message': 'Refund request submitted successfully'
        })
        
    except Exception as e:
        session.rollback()
        logger.error(f"Error requesting refund: {str(e)}")
        return jsonify({
            'success': False,
            'error': 'Failed to request refund'
        }), 500

def generate_invoice_pdf(booking, passenger, flight, payment):
    """Generate PDF invoice using xhtml2pdf"""
    if not HAS_XHTML2PDF:
        return None
        
    try:
        # Create HTML template for invoice
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <style>
                body {{ font-family: Arial, sans-serif; margin: 40px; }}
                .header {{ text-align: center; border-bottom: 2px solid #333; padding-bottom: 20px; }}
                .logo {{ font-size: 24px; font-weight: bold; color: #1877f2; }}
                .section {{ margin: 20px 0; }}
                .row {{ display: flex; justify-content: space-between; margin: 10px 0; }}
                .label {{ font-weight: bold; }}
                .total {{ font-size: 18px; font-weight: bold; border-top: 1px solid #333; padding-top: 10px; }}
                .footer {{ margin-top: 40px; text-align: center; color: #666; }}
            </style>
        </head>
        <body>
            <div class="header">
                <div class="logo">FlyGo Airlines</div>
                <h1>Flight Booking Invoice</h1>
            </div>
            
            <div class="section">
                <h2>Booking Information</h2>
                <div class="row">
                    <span class="label">Booking Reference:</span>
                    <span>{booking.booking_reference}</span>
                </div>
                <div class="row">
                    <span class="label">Ticket Number:</span>
                    <span>{booking.ticket_number}</span>
                </div>
                <div class="row">
                    <span class="label">Booking Date:</span>
                    <span>{booking.booking_date.strftime('%Y-%m-%d %H:%M')}</span>
                </div>
            </div>
            
            <div class="section">
                <h2>Passenger Information</h2>
                <div class="row">
                    <span class="label">Name:</span>
                    <span>{passenger.first_name} {passenger.last_name}</span>
                </div>
                <div class="row">
                    <span class="label">Email:</span>
                    <span>{passenger.email}</span>
                </div>
                <div class="row">
                    <span class="label">Phone:</span>
                    <span>{passenger.phone}</span>
                </div>
                <div class="row">
                    <span class="label">Passport:</span>
                    <span>{passenger.passport_number}</span>
                </div>
            </div>
            
            <div class="section">
                <h2>Flight Details</h2>
                <div class="row">
                    <span class="label">Flight Number:</span>
                    <span>{flight.flight_number}</span>
                </div>
                <div class="row">
                    <span class="label">Route:</span>
                    <span>{flight.departure_city} ({flight.departure_airport}) → {flight.destination_city} ({flight.destination_airport})</span>
                </div>
                <div class="row">
                    <span class="label">Departure:</span>
                    <span>{flight.departure_time.strftime('%Y-%m-%d %H:%M')}</span>
                </div>
                <div class="row">
                    <span class="label">Arrival:</span>
                    <span>{flight.arrival_time.strftime('%Y-%m-%d %H:%M')}</span>
                </div>
                <div class="row">
                    <span class="label">Duration:</span>
                    <span>{flight.duration}</span>
                </div>
                <div class="row">
                    <span class="label">Class:</span>
                    <span>{flight.travel_class}</span>
                </div>
            </div>
            
            <div class="section">
                <h2>Payment Information</h2>
                <div class="row">
                    <span class="label">Payment Method:</span>
                    <span>{payment.payment_method}</span>
                </div>
                <div class="row">
                    <span class="label">Payment Reference:</span>
                    <span>{payment.payment_reference}</span>
                </div>
                <div class="row">
                    <span class="label">Payment Date:</span>
                    <span>{payment.payment_date.strftime('%Y-%m-%d %H:%M')}</span>
                </div>
                <div class="row total">
                    <span class="label">Total Amount:</span>
                    <span>${booking.total_amount}</span>
                </div>
            </div>
            
            <div class="footer">
                <p>Thank you for choosing FlyGo Airlines!</p>
                <p>For any queries, contact support@flygo.com</p>
            </div>
        </body>
        </html>
        """
        
        # Create PDF in memory
        pdf_buffer = io.BytesIO()
        pisa_status = pisa.CreatePDF(html_content, dest=pdf_buffer)
        
        if pisa_status.err:
            raise Exception("PDF generation failed")
        
        pdf_buffer.seek(0)
        return pdf_buffer
        
    except Exception as e:
        logger.error(f"Error generating PDF with xhtml2pdf: {str(e)}")
        return None

def generate_text_invoice(booking, passenger, flight, payment):
    """Generate text invoice as fallback"""
    text_content = f"""
FlyGo Airlines - Flight Booking Invoice
========================================

Booking Information:
-------------------
Booking Reference: {booking.booking_reference}
Ticket Number: {booking.ticket_number}
Booking Date: {booking.booking_date.strftime('%Y-%m-%d %H:%M')}

Passenger Information:
---------------------
Name: {passenger.first_name} {passenger.last_name}
Email: {passenger.email}
Phone: {passenger.phone}
Passport: {passenger.passport_number}

Flight Details:
---------------
Flight Number: {flight.flight_number}
Route: {flight.departure_city} ({flight.departure_airport}) → {flight.destination_city} ({flight.destination_airport})
Departure: {flight.departure_time.strftime('%Y-%m-%d %H:%M')}
Arrival: {flight.arrival_time.strftime('%Y-%m-%d %H:%M')}
Duration: {flight.duration}
Class: {flight.travel_class}

Payment Information:
-------------------
Payment Method: {payment.payment_method}
Payment Reference: {payment.payment_reference}
Payment Date: {payment.payment_date.strftime('%Y-%m-%d %H:%M')}
Total Amount: ${booking.total_amount}

Thank you for choosing FlyGo Airlines!
For any queries, contact support@flygo.com
    """
    return text_content


@flight_bp.route('/debug-user-data')
@login_required
def debug_user_data():
    """Debug route to check user data and bookings"""
    from main import engine, Booking, Passenger, User
    
    Session = sessionmaker(bind=engine)
    session = Session()
    
    # Check current user
    current_user_data = {
        'user_id': current_user.id,
        'username': current_user.username,
        'email': current_user.email
    }
    
    # Check bookings by user_id
    user_bookings = session.query(Booking).filter(
        Booking.user_id == current_user.id
    ).all()
    
    # Check passengers with user's email
    passenger_bookings = session.query(Booking).join(Passenger).filter(
        Passenger.email == current_user.email
    ).all()
    
    # Check all passengers
    all_passengers = session.query(Passenger).all()
    
    session.close()
    
    return jsonify({
        'current_user': current_user_data,
        'user_bookings_count': len(user_bookings),
        'user_booking_refs': [b.booking_reference for b in user_bookings],
        'passenger_bookings_count': len(passenger_bookings),
        'passenger_booking_refs': [b.booking_reference for b in passenger_bookings],
        'all_passengers': [{'id': p.id, 'email': p.email, 'name': f"{p.first_name} {p.last_name}"} for p in all_passengers]
    })

@flight_bp.route('/migrate-existing-bookings')
@login_required
def migrate_existing_bookings():
    """Migrate existing bookings to current user"""
    try:
        from main import engine, Booking, Passenger
        
        Session = sessionmaker(bind=engine)
        session = Session()
        
        # Find passengers with current user's email
        user_passengers = session.query(Passenger).filter(
            Passenger.email == current_user.email
        ).all()
        
        migrated_count = 0
        for passenger in user_passengers:
            # Update all bookings for this passenger to link to current user
            bookings = session.query(Booking).filter(
                Booking.passenger_id == passenger.id
            ).all()
            
            for booking in bookings:
                booking.user_id = current_user.id
                migrated_count += 1
        
        session.commit()
        session.close()
        
        return jsonify({
            'success': True,
            'message': f'Migrated {migrated_count} bookings to user {current_user.id}'
        })
        
    except Exception as e:
        session.rollback()
        logger.error(f"Error migrating bookings: {str(e)}")
        return jsonify({
            'success': False,
            'error': f'Migration failed: {str(e)}'
        }), 500
    

    # Admin routes
@flight_bp.route('/api/admin/pending-refunds')
@login_required
def admin_pending_refunds():
    """Get all pending refund requests for admin"""
    if current_user.is_admin != 1:
        return jsonify({'success': False, 'error': 'Admin access required'}), 403
    
    try:
        from main import engine, Booking, Passenger, Flight, User
        
        Session = sessionmaker(bind=engine)
        session = Session()
        
        # Get pending refunds
        pending_refunds = session.query(Booking).filter(
            Booking.refund_requested == True,
            Booking.refund_status == 'Pending'
        ).all()
        
        refunds_data = []
        for booking in pending_refunds:
            flight = session.query(Flight).filter_by(id=booking.flight_id).first()
            passenger = session.query(Passenger).filter_by(id=booking.passenger_id).first()
            user = session.query(User).filter_by(id=booking.user_id).first()
            
            if flight and passenger:
                refunds_data.append({
                    'booking_reference': booking.booking_reference,
                    'passenger_name': f"{passenger.first_name} {passenger.last_name}",
                    'flight_route': f"{flight.departure_city} → {flight.destination_city}",
                    'amount': float(booking.total_amount),
                    'request_date': booking.refund_date.strftime('%Y-%m-%d %H:%M') if booking.refund_date else 'N/A',
                    'user_email': user.email if user else 'N/A'
                })
        
        # Get stats
        total_bookings = session.query(Booking).count()
        pending_refunds_count = session.query(Booking).filter(
            Booking.refund_requested == True,
            Booking.refund_status == 'Pending'
        ).count()
        
        session.close()
        
        return jsonify({
            'success': True,
            'refunds': refunds_data,
            'stats': {
                'pending_refunds': pending_refunds_count,
                'total_bookings': total_bookings
            }
        })
        
    except Exception as e:
        logger.error(f"Error fetching pending refunds: {str(e)}")
        return jsonify({
            'success': False,
            'error': 'Failed to fetch pending refunds'
        }), 500

@flight_bp.route('/api/admin/all-bookings')
@login_required
def admin_all_bookings():
    """Get all bookings for admin management"""
    if current_user.is_admin != 1:
        return jsonify({'success': False, 'error': 'Admin access required'}), 403
    
    try:
        from main import engine, Booking, Passenger, Flight, User
        
        Session = sessionmaker(bind=engine)
        session = Session()
        
        filter_type = request.args.get('filter', 'all')
        
        # Base query
        query = session.query(Booking)
        
        # Apply filters
        if filter_type == 'pending_refund':
            query = query.filter(Booking.refund_requested == True, Booking.refund_status == 'Pending')
        elif filter_type == 'confirmed':
            query = query.filter(Booking.status == 'Confirmed')
        elif filter_type == 'cancelled':
            query = query.filter(Booking.status == 'Cancelled')
        
        bookings = query.order_by(Booking.booking_date.desc()).all()
        
        bookings_data = []
        for booking in bookings:
            flight = session.query(Flight).filter_by(id=booking.flight_id).first()
            passenger = session.query(Passenger).filter_by(id=booking.passenger_id).first()
            user = session.query(User).filter_by(id=booking.user_id).first()
            
            if flight and passenger:
                bookings_data.append({
                    'booking_reference': booking.booking_reference,
                    'passenger_name': f"{passenger.first_name} {passenger.last_name}",
                    'flight_route': f"{flight.departure_city} → {flight.destination_city}",
                    'total_amount': float(booking.total_amount),
                    'booking_date': booking.booking_date.strftime('%Y-%m-%d %H:%M'),
                    'status': booking.status,
                    'refund_requested': booking.refund_requested,
                    'refund_status': booking.refund_status,
                    'user_email': user.email if user else 'N/A'
                })
        
        session.close()
        
        return jsonify({
            'success': True,
            'bookings': bookings_data
        })
        
    except Exception as e:
        logger.error(f"Error fetching all bookings: {str(e)}")
        return jsonify({
            'success': False,
            'error': 'Failed to fetch bookings'
        }), 500

@flight_bp.route('/api/admin/users')
@login_required
def admin_users():
    """Get all users for admin management"""
    if current_user.is_admin != 1:
        return jsonify({'success': False, 'error': 'Admin access required'}), 403
    
    try:
        from main import engine, User, Booking
        
        Session = sessionmaker(bind=engine)
        session = Session()
        
        users = session.query(User).all()
        
        users_data = []
        for user in users:
            # Count user's bookings
            booking_count = session.query(Booking).filter(Booking.user_id == user.id).count()
            
            users_data.append({
                'id': user.id,
                'username': user.username,
                'email': user.email,
                'is_admin': user.is_admin == 1,
                'total_bookings': booking_count
            })
        
        session.close()
        
        return jsonify({
            'success': True,
            'users': users_data
        })
        
    except Exception as e:
        logger.error(f"Error fetching users: {str(e)}")
        return jsonify({
            'success': False,
            'error': 'Failed to fetch users'
        }), 500

@flight_bp.route('/api/admin/process-refund', methods=['POST'])
@login_required
def admin_process_refund():
    """Process refund (approve or reject)"""
    if current_user.is_admin != 1:
        return jsonify({'success': False, 'error': 'Admin access required'}), 403
    
    try:
        data = request.get_json()
        booking_ref = data.get('booking_reference')
        action = data.get('action')  # 'approved' or 'rejected'
        
        from main import engine, Booking
        
        Session = sessionmaker(bind=engine)
        session = Session()
        
        booking = session.query(Booking).filter_by(booking_reference=booking_ref).first()
        
        if not booking:
            return jsonify({'success': False, 'error': 'Booking not found'}), 404
        
        if action == 'approved':
            booking.refund_status = 'Completed'
            booking.status = 'Cancelled'
            # Here you would typically integrate with payment gateway for actual refund
        elif action == 'rejected':
            booking.refund_status = 'Rejected'
        
        session.commit()
        session.close()
        
        return jsonify({
            'success': True,
            'message': f'Refund {action} successfully'
        })
        
    except Exception as e:
        session.rollback()
        logger.error(f"Error processing refund: {str(e)}")
        return jsonify({
            'success': False,
            'error': 'Failed to process refund'
        }), 500

@flight_bp.route('/api/admin/cancel-booking', methods=['POST'])
@login_required
def admin_cancel_booking():
    """Cancel a booking as admin"""
    if current_user.is_admin != 1:
        return jsonify({'success': False, 'error': 'Admin access required'}), 403
    
    try:
        data = request.get_json()
        booking_ref = data.get('booking_reference')
        
        from main import engine, Booking
        
        Session = sessionmaker(bind=engine)
        session = Session()
        
        booking = session.query(Booking).filter_by(booking_reference=booking_ref).first()
        
        if not booking:
            return jsonify({'success': False, 'error': 'Booking not found'}), 404
        
        booking.status = 'Cancelled'
        session.commit()
        session.close()
        
        return jsonify({
            'success': True,
            'message': 'Booking cancelled successfully'
        })
        
    except Exception as e:
        session.rollback()
        logger.error(f"Error cancelling booking: {str(e)}")
        return jsonify({
            'success': False,
            'error': 'Failed to cancel booking'
        }), 500