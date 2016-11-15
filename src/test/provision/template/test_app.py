from mock import MagicMock

from spacel.model import SpaceServicePort, SpaceDockerService
from spacel.provision.app.alarm import AlarmFactory
from spacel.provision.app.app_spot import AppSpotTemplateDecorator
from spacel.provision.app.db import CacheFactory, RdsFactory
from spacel.provision.template.app import AppTemplate
from spacel.security import AcmCertificates, KmsKeyFactory
from test import ORBIT_REGION
from test.provision.template import BaseTemplateTest
from test.security import KEY_ARN

DOMAIN_NAME = 'test-app-test-orbit.test.com'
SUBNET_GROUP = 'subnet-123456'


class TestAppTemplate(BaseTemplateTest):
    def setUp(self):
        super(TestAppTemplate, self).setUp()
        self.orbit_region.bastion_sg = 'sg-123tes'

    def _template_name(self):
        return 'elb-service'

    def _cache(self, ami_finder):
        self.alarms = MagicMock(spec=AlarmFactory)
        self.caches = MagicMock(spec=CacheFactory)
        self.rds = MagicMock(spec=RdsFactory)
        self.spot = MagicMock(spec=AppSpotTemplateDecorator)
        self.acm = MagicMock(spec=AcmCertificates)
        self.kms_key = MagicMock(spec=KmsKeyFactory)
        self.kms_key.get_key.return_value = None
        return AppTemplate(ami_finder, self.alarms, self.caches, self.rds,
                           self.spot, self.acm, self.kms_key)

    def test_app(self):
        app, _ = self.cache.app(self.app_region)

        app_resources = len(app['Resources'])
        self.assertEquals(self.base_resources, app_resources)
        params = app['Parameters']
        resources = app['Resources']

        self.assertEquals(params['VirtualHostDomain']['Default'], 'test.com.')

        self.assertEquals(params['VirtualHost']['Default'], DOMAIN_NAME)

        block_devs = resources['Lc']['Properties']['BlockDeviceMappings']
        self.assertEquals(1, len(block_devs))

    def test_app_domain(self):
        self.app_region.hostnames = ('app.test.com',)

        app, _ = self.cache.app(self.app_region)

        params = app['Parameters']
        self.assertEquals(params['VirtualHostDomain']['Default'], 'test.com.')
        self.assertEquals(params['VirtualHost']['Default'], 'app.test.com')

    def test_app_bastion(self):
        app, _ = self.cache.app(self.app_region)

        bastion_sg_param = app['Parameters']['BastionSecurityGroup']['Default']
        self.assertEqual('sg-123tes', bastion_sg_param)

    def test_app_no_bastion(self):
        self.orbit_region.bastion_sg = None

        app, _ = self.cache.app(self.app_region)

        self.assertNotIn('BastionSecurityGroup', app['Parameters'])

    def test_app_availability(self):
        self.app_region.instance_availability = 'internet-facing'
        self.orbit.public_instance_subnets = MagicMock(return_value=('test',))

        app, _ = self.cache.app(self.app_region)

        public_addr = (app['Resources']['Lc']['Properties']
                       ['AssociatePublicIpAddress'])
        self.assertEqual(True, public_addr)

    def test_app_no_load_balancer(self):
        self.app_region.elb_availability = 'disabled'

        app, _ = self.cache.app(self.app_region)

        self.assertEqual(False, app['Parameters']['PublicElb']['Default'])
        self.assertEqual(False, app['Parameters']['PrivateElb']['Default'])
        self.assertNotIn('PublicElb', app['Resources'])
        self.assertNotIn('PrivateElb', app['Resources'])
        self.assertNotIn('ElbSg', app['Resources'])
        self.assertNotIn('DnsRecord', app['Resources'])
        self.assertNotIn('ElbHealthPolicy', app['Resources'])
        self.assertNotIn('LoadBalancerNames', app['Resources']['Asg']
        ['Properties'])
        self.assertNotIn('PrivateElbSubnet01', app['Parameters'])
        self.assertNotIn('PublicElbSubnet01', app['Parameters'])
        self.assertEqual('disabled', app['Parameters']['ElbScheme']['Default'])
        self.assertEqual('EC2', app['Resources']['Asg']['Properties']
        ['HealthCheckType'])

    def test_app_private_ports(self):
        self.app_region.private_ports = {123: ['TCP']}

        app, _ = self.cache.app(self.app_region)

        sg_properties = app['Resources']['PrivatePort123TCP']['Properties']
        self.assertEquals('123', sg_properties['FromPort'])
        self.assertEquals('123', sg_properties['ToPort'])

    def test_app_private_ports_split(self):
        self.app_region.private_ports = {'123-456': ['TCP']}

        app, _ = self.cache.app(self.app_region)

        sg_properties = app['Resources']['PrivatePort123to456TCP']['Properties']
        self.assertEquals('123', sg_properties['FromPort'])
        self.assertEquals('456', sg_properties['ToPort'])

    def test_app_public_ports_ssl_cert(self):
        self.app.public_ports = {
            443: SpaceServicePort(443, {
                'certificate': '123456'
            })
        }

        app, _ = self.cache.app(self.app_region)

        self.acm.get_certificate.assert_not_called()

    def test_app_public_ports_ssl_acm(self):
        self.app_region.public_ports = {
            443: SpaceServicePort(443, {})
        }
        app, _ = self.cache.app(self.app_region)

        self.acm.get_certificate.assert_called_with(ORBIT_REGION, DOMAIN_NAME)

    def test_app_public_ports_ssl_not_found(self):
        self.app_region.public_ports = {
            443: SpaceServicePort(443, {})
        }
        self.acm.get_certificate.return_value = None

        self.assertRaises(Exception, self.cache.app, self.app_region)

    def test_app_instance_storage(self):
        self.app_region.instance_type = 'c1.medium'

        app, _ = self.cache.app(self.app_region)

        block_devs = app['Resources']['Lc']['Properties']['BlockDeviceMappings']
        self.assertEquals(2, len(block_devs))

    def test_app_cache_subnet_group(self):
        self.orbit_region.private_cache_subnet_group = SUBNET_GROUP

        app, _ = self.cache.app(self.app_region)
        self.assertEquals(SUBNET_GROUP, (app['Parameters']
                                         ['PrivateCacheSubnetGroup']
                                         ['Default']))

    def test_app_public_rds_subnet_group(self):
        self.orbit_region.public_rds_subnet_group = SUBNET_GROUP

        app, _ = self.cache.app(self.app_region)
        self.assertEquals(SUBNET_GROUP, (app['Parameters']
                                         ['PublicRdsSubnetGroup']
                                         ['Default']))

    def test_app_private_rds_subnet_group(self):
        self.orbit_region.private_rds_subnet_group = SUBNET_GROUP

        app, _ = self.cache.app(self.app_region)
        self.assertEquals(SUBNET_GROUP, (app['Parameters']
                                         ['PrivateRdsSubnetGroup']
                                         ['Default']))

    def test_app_min_in_service(self):
        self.app_region.instance_min = 2
        self.app_region.instance_max = 2
        app, _ = self.cache.app(self.app_region)

        self.assertEquals(1, (app['Parameters']
                              ['InstanceMinInService']
                              ['Default']))

    def test_user_data(self):
        params = {}

        user_data = self.cache._user_data(params, self.app_region)

        self.assertEquals('', user_data)

    def test_user_data_services(self):
        params = {'VolumeSupport': {}}
        self.app_region.services = {
            'test.service': SpaceDockerService('test.service', 'test/test',
                                               environment={'FOO': 'bar'})
        }

        user_data = self.cache._user_data(params, self.app_region)

        self.assertIn('"test.service"', user_data)
        self.assertNotIn('Default', params['VolumeSupport'])

    def test_user_data_volumes(self):
        params = {'VolumeSupport': {}}
        self.app_region.volumes = {'test': {'count': 2, 'size': 2}}

        user_data = self.cache._user_data(params, self.app_region)

        self.assertIn('"test"', user_data)
        self.assertEquals(params['VolumeSupport']['Default'], 'true')

    def test_add_kms_iam_policy_noop(self):
        resources = {}
        self.cache._add_kms_iam_policy(self.app_region, resources)

        self.assertEquals({}, resources)

    def test_add_kms_iam_policy(self):
        self.kms_key.get_key.return_value = KEY_ARN
        resources = {}
        self.cache._add_kms_iam_policy(self.app_region, resources)

        self.assertEquals(1, len(resources))
        self.assertIn('KmsKeyPolicy', resources)
