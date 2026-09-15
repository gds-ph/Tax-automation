"""Bearer-only API. Browser sessions never authorize worker endpoints."""
import hashlib
import json
import logging
import uuid
from functools import wraps
from django.http import JsonResponse, HttpResponse
from django.db import models, OperationalError, IntegrityError
from django.core.exceptions import ValidationError, RequestDataTooBig
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.debug import sensitive_variables
from .models import Agent, PreparationAttempt
from . import worker_services as services
from .worker_policy import MAX_PDF_BYTES, POLL_SECONDS

logger=logging.getLogger(__name__)


def error_response(code,message,status):
    return JsonResponse({'error':code,'message':message},status=status)


def endpoint(method):
    def decorate(view):
        @csrf_exempt
        @wraps(view)
        @sensitive_variables()
        def wrapped(request,*args,**kwargs):
            try:
                header=request.headers.get('Authorization','')
                parts=header.split()
                if len(parts)!=2 or parts[0]!='Bearer' or not 64<=len(parts[1])<=200:
                    raise services.WorkerError('unauthorized','A valid worker bearer token is required.',401)
                agent=Agent.objects.filter(token_hash=hashlib.sha256(parts[1].encode()).hexdigest(),is_active=True).first()
                if not agent or not agent.check_token(parts[1]):
                    raise services.WorkerError('unauthorized','A valid worker bearer token is required.',401)
                if request.method!=method:
                    response=error_response('method_not_allowed',f'Use {method}.',405)
                    response['Allow']=method
                else:
                    # Credential material is never logged or placed in query strings.
                    models.QuerySet.update(Agent.objects.filter(pk=agent.pk),last_seen_at=timezone.now())
                    response=view(request,agent,*args,**kwargs)
            except services.WorkerError as error:
                response=error_response(error.code,error.message,error.status)
            except (ValueError,TypeError,KeyError,json.JSONDecodeError,RequestDataTooBig):
                response=error_response('invalid_request','Request body or headers are invalid.',400)
            except ValidationError:
                response=error_response('validation_failed','The work order failed validation. Reload or request operator review.',409)
            except (OperationalError,IntegrityError):
                response=error_response('write_conflict','A concurrent write is in progress. Retry the same request ID after a short delay.',409)
            except Exception:
                # Even DEBUG=True must not expose headers, token values or taxpayer data.
                logger.error('Worker API request failed; no request data logged.')
                response=error_response('internal_error','The request could not be completed. Preserve the request ID and check the server.',500)
            response['Cache-Control']='no-store, private'
            response['X-Content-Type-Options']='nosniff'
            if response.status_code==401:
                response['WWW-Authenticate']='Bearer'
            return response
        return wrapped
    return decorate


def body(request,allowed,required=None):
    if request.content_type!='application/json':
        raise services.WorkerError('content_type','Use application/json.',415)
    if int(request.headers.get('Content-Length','0'))>16384:
        raise services.WorkerError('body_too_large','JSON requests are limited to 16 KiB.',413)
    raw=request.read(16385)
    if len(raw)>16384:
        raise services.WorkerError('body_too_large','JSON requests are limited to 16 KiB.',413)
    value=json.loads(raw)
    if not isinstance(value,dict) or set(value)-set(allowed) or not set(required or allowed)<=set(value):
        raise services.WorkerError('invalid_fields','Unexpected or missing JSON fields.',400)
    return value


@endpoint('GET')
def health(request,agent):
    return JsonResponse({'status':'ok','agent':agent.name,'api_version':1,'poll_seconds':POLL_SECONDS,'submission_enabled':False})


@endpoint('POST')
def claim(request,agent):
    data=body(request,{'request_id','automation_keys'})
    attempt=services.claim(agent=agent,request_id=uuid.UUID(data['request_id']),automation_keys=data['automation_keys'])
    if not attempt:
        return HttpResponse(status=204)
    return JsonResponse(services.payload(attempt))


@endpoint('GET')
def current(request,agent):
    attempt=PreparationAttempt.objects.select_related('work_order','snapshot').filter(agent=agent,state='RUNNING').first()
    if not attempt:
        return HttpResponse(status=204)
    # Diagnostic only: deliberately omit inputs and lease token to prevent restart-by-poll.
    return JsonResponse({'AttemptId':str(attempt.pk),'WorkOrderId':attempt.work_order.work_order_id,
        'State':attempt.state,'LeaseExpired':attempt.lease_expires_at<=timezone.now(),
        'message':'Consult the local worker journal. Do not rerun an already started desktop flow.'})


@endpoint('POST')
def renew(request,agent,attempt_id):
    data=body(request,{'lease_token'})
    attempt=services.renew(agent=agent,attempt_id=attempt_id,lease_token=data['lease_token'])
    return JsonResponse({'LeaseExpiresAt':attempt.lease_expires_at.isoformat()})


@endpoint('PUT')
def pdf(request,agent,attempt_id):
    if request.content_type!='application/pdf':
        raise services.WorkerError('content_type','Upload raw PDF bytes with application/pdf.',415)
    if int(request.headers.get('Content-Length','0'))>MAX_PDF_BYTES:
        raise services.WorkerError('file_too_large','PDF exceeds the 25 MiB limit.',413)
    digest=services.upload_pdf(agent=agent,attempt_id=attempt_id,lease_token=request.headers.get('X-Lease-Token',''),
        source=request,expected_sha256=request.headers.get('X-PDF-SHA256',''))
    return JsonResponse({'sha256':digest,'recorded':True})


@endpoint('POST')
def result(request,agent,attempt_id):
    data=body(request,{'lease_token','PreparationStatusOutput','PreparedPdfPath','SavedXmlPath'},required={'lease_token','PreparationStatusOutput'})
    lease=data.pop('lease_token')
    order=services.record_result(agent=agent,attempt_id=attempt_id,lease_token=lease,data=data)
    return JsonResponse({'WorkOrderId':order.work_order_id,'Status':order.status,'PdfSha256':order.prepared_pdf_sha256})
